"""Versioned assessment rule-release draft contracts."""

from dataclasses import replace
from decimal import Decimal
from datetime import datetime
import hashlib
import json
import sqlite3
from zoneinfo import ZoneInfo

import pytest

import models
from assessment.contracts import RuleReleaseFilters
from pagination import PageRequest
from repository import DataConflictError
from rule_release_repository import (
    copy_active_release,
    load_release_draft,
    query_rule_releases,
    save_release_draft,
)
from rule_release_seed import reconcile_initial_v2_release
from rule_release_validation import (
    _text,
    compile_release_snapshot,
    normalize_release_draft,
    validate_release_draft,
)


SHANGHAI_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _RecordingEmptyReleaseDb:
    def __init__(self):
        self.statements = []
        self.rolled_back = False

    def execute(self, statement, parameters=()):
        self.statements.append(statement)
        if "sqlite_master" in statement:
            return _Result((1,))
        return _Result()

    def rollback(self):
        self.rolled_back = True


def test_initialization_creates_one_active_published_release_snapshot(db):
    """Removing migration 015 or startup reconciliation must break this contract."""
    row = db.execute(
        "SELECT v.status,v.validated_digest,s.sha256 "
        "FROM active_assessment_version a "
        "JOIN assessment_versions v ON v.id=a.assessment_version_id "
        "JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id "
        "WHERE a.singleton_id=1"
    ).fetchone()

    assert row is not None
    assert tuple(row) == ("published", row[2], row[2])


def test_initial_reconciliation_locks_before_reading_pointer_or_root():
    """Concurrent startup decisions must occur inside the same IMMEDIATE transaction."""
    database = _RecordingEmptyReleaseDb()

    with pytest.raises(RuntimeError, match="unavailable"):
        reconcile_initial_v2_release(database, SHANGHAI_NOW)

    assert database.statements[1] == "BEGIN IMMEDIATE"
    assert database.rolled_back is True


def test_copy_active_release_has_exact_runtime_cardinality(db):
    """Dropping any frozen V2 child collection must make a copied draft incomplete."""
    draft_id = copy_active_release(
        code="v2.1-draft", name="V2.1 草稿", actor="admin", now=SHANGHAI_NOW
    )
    draft = load_release_draft(draft_id)

    assert len(draft.industries) == 4
    assert len(draft.scenarios) == 13
    assert len(draft.services) == 6
    assert len(draft.questions) == 12
    assert all(len(question.options) == 4 for question in draft.questions)
    assert draft.created_at == "2026-09-01 10:00:00"
    assert draft.updated_at == "2026-09-01 10:00:00"


def test_branch_scoped_scenario_links_match_legacy_authority_and_roundtrip(db):
    """Department/pain codes shared by industries must retain their owning branch."""
    active_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    active = load_release_draft(active_id)
    expected_departments = {}
    for row in db.execute(
        "SELECT s.code scenario_code,i.code branch_code,d.code "
        "FROM scenario_departments x JOIN scenarios s ON s.id=x.scenario_id "
        "JOIN departments d ON d.id=x.department_id "
        "JOIN industries i ON i.id=d.industry_id "
        "ORDER BY s.sort_order,i.sort_order,d.sort_order"
    ):
        expected_departments.setdefault(row["scenario_code"], []).append(
            (row["branch_code"], row["code"])
        )

    for scenario in active.scenarios:
        assert [
            (item.branch_code, item.code) for item in scenario.department_links
        ] == expected_departments[scenario.code]

    draft_id = _copy("v2-branch-roundtrip")
    draft = load_release_draft(draft_id)
    before = tuple(
        (
            item.code,
            tuple((link.branch_code, link.code) for link in item.department_links),
            tuple((link.branch_code, link.code) for link in item.pain_links),
        )
        for item in draft.scenarios
    )
    save_release_draft(draft_id, draft.lock_version, draft, SHANGHAI_NOW)
    after = load_release_draft(draft_id)
    assert tuple(
        (
            item.code,
            tuple((link.branch_code, link.code) for link in item.department_links),
            tuple((link.branch_code, link.code) for link in item.pain_links),
        )
        for item in after.scenarios
    ) == before


def test_scenario_department_rejects_forged_branch_ownership(db):
    draft_id = _copy("v2-forged-branch")
    scenario = db.execute(
        "SELECT id FROM assessment_release_scenarios WHERE assessment_version_id=? "
        "ORDER BY sort_order LIMIT 1",
        (draft_id,),
    ).fetchone()[0]
    forged = db.execute(
        "SELECT i.code,d.code FROM assessment_release_departments d "
        "JOIN assessment_release_industries i ON i.id=d.industry_id "
        "WHERE d.assessment_version_id=? AND NOT EXISTS("
        " SELECT 1 FROM assessment_release_scenario_branches b "
        " WHERE b.scenario_id=? AND b.branch_code=i.code) LIMIT 1",
        (draft_id, scenario),
    ).fetchone()
    sort_order = db.execute(
        "SELECT COALESCE(MAX(sort_order),0)+1 FROM assessment_release_scenario_departments "
        "WHERE scenario_id=?",
        (scenario,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO assessment_release_scenario_departments "
            "(assessment_version_id,scenario_id,branch_code,department_code,sort_order) "
            "VALUES (?,?,?,?,?)",
            (draft_id, scenario, forged[0], forged[1], sort_order),
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda draft: replace(draft, scenarios=draft.scenarios[:-1]), "scenario_cardinality"),
        (lambda draft: replace(draft, services=draft.services[:-1]), "service_cardinality"),
        (
            lambda draft: replace(
                draft,
                scenarios=tuple(
                    replace(item, fallback_only=False)
                    if item.code == "data_process_foundation"
                    else item
                    for item in draft.scenarios
                ),
            ),
            "fallback_policy",
        ),
        (
            lambda draft: replace(
                draft,
                services=(replace(draft.services[0], min_budget=Decimal("0")),)
                + draft.services[1:],
            ),
            "service_budget",
        ),
        (
            lambda draft: replace(
                draft,
                scenarios=(
                    replace(
                        draft.scenarios[0],
                        department_links=draft.scenarios[0].department_links
                        + (draft.scenarios[0].department_links[0],),
                    ),
                )
                + draft.scenarios[1:],
            ),
            "scenario_links",
        ),
    ),
)
def test_schema_2_exact_cardinality_fallback_budget_and_relation_invariants(
    db, mutation, error
):
    active_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    draft = load_release_draft(active_id)

    assert error in validate_release_draft(mutation(draft))


def test_schema_2_has_the_single_required_fallback_and_legal_service_refs(db):
    active_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    draft = load_release_draft(active_id)
    fallback = [item for item in draft.scenarios if item.code == "data_process_foundation"]

    assert len(draft.scenarios) == 13
    assert len(draft.services) == 6
    assert len(fallback) == 1 and fallback[0].fallback_only is True
    assert {item.service_code for item in draft.scenarios} <= {
        item.code for item in draft.services
    }


@pytest.mark.parametrize(
    ("table", "column"),
    (
        ("assessment_release_scenario_budgets", "budget_code"),
        ("assessment_release_scenario_risks", "risk_code"),
    ),
)
def test_direct_release_relation_inserts_reject_codes_outside_release_domain(
    db, table, column
):
    draft_id = _copy(f"v2-domain-{column}")
    scenario = db.execute(
        "SELECT id FROM assessment_release_scenarios WHERE assessment_version_id=? "
        "ORDER BY sort_order LIMIT 1",
        (draft_id,),
    ).fetchone()[0]
    order = db.execute(
        f"SELECT COALESCE(MAX(sort_order),0)+1 FROM {table} WHERE scenario_id=?",
        (scenario,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="domain"):
        db.execute(
            f"INSERT INTO {table} "
            f"(assessment_version_id,scenario_id,{column},sort_order) VALUES (?,?,?,?)",
            (draft_id, scenario, "unknown_domain_code", order),
        )


def _changed_public_label(draft, family):
    labels = draft.public_labels
    if family == "roi_options":
        nested = {group: dict(values) for group, values in labels.roi_options.items()}
        group = next(iter(nested))
        code = next(iter(nested[group]))
        nested[group][code] = nested[group][code] + "（新版）"
        changed = replace(labels, roi_options=nested)
    else:
        values = dict(getattr(labels, family))
        code = next(iter(values))
        values[code] = values[code] + "（新版）"
        changed = replace(labels, **{family: values})
    return replace(draft, public_labels=changed)


@pytest.mark.parametrize(
    "family",
    (
        "risk_labels",
        "risk_explanations",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
        "roi_options",
    ),
)
def test_each_public_label_family_is_release_owned_and_changes_digest(db, family):
    draft_id = _copy(f"v2-label-{family}")
    draft = load_release_draft(draft_id)
    original = compile_release_snapshot(draft)
    changed = _changed_public_label(draft, family)

    assert validate_release_draft(changed) == ()
    assert compile_release_snapshot(changed).sha256 != original.sha256
    save_release_draft(draft_id, draft.lock_version, changed, SHANGHAI_NOW)
    loaded = load_release_draft(draft_id)
    expected = normalize_release_draft(changed)
    assert getattr(loaded.public_labels, family) == getattr(
        expected.public_labels, family
    )


def test_public_label_domains_are_complete_in_canonical_snapshot(db):
    active_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    draft = load_release_draft(active_id)
    labels = draft.public_labels
    canonical = json.loads(compile_release_snapshot(replace(draft, status="draft")).canonical_json)

    assert tuple(labels.dimensions) == (
        "business_value",
        "process",
        "data",
        "systems",
        "organization",
        "delivery",
    )
    assert tuple(labels.maturities) == ("explore", "pilot", "scale", "collaborate")
    assert tuple(labels.integrations) == ("low", "medium", "high")
    assert set(labels.risk_labels) == set(labels.risk_explanations)
    assert set(labels.roi_groups) == set(labels.roi_options)
    assert canonical["public_labels"]["risk_labels"] == dict(labels.risk_labels)


def test_high_precision_and_extremely_large_finite_roi_decimals_roundtrip(db):
    draft_id = _copy("v2-decimal-lossless")
    draft = load_release_draft(draft_id)
    precise = (
        Decimal("12345678901234567890.1234567890123456789012345678901"),
        Decimal("12345678901234567890.2234567890123456789012345678901"),
        Decimal("9.999999999999999999999999999999999999999E+900"),
    )
    unit = (
        Decimal("0.123456789012345678901234567890123456789"),
        Decimal("0.223456789012345678901234567890123456789"),
        Decimal("0.323456789012345678901234567890123456789"),
    )
    roi_ranges = {
        group: dict(values) for group, values in draft.roi_ranges.items()
    }
    option_code = next(iter(roi_ranges["headcount"]))
    roi_ranges["headcount"][option_code] = precise
    changed = replace(
        draft,
        roi_ranges=roi_ranges,
        scenarios=(replace(draft.scenarios[0], efficiency=unit),) + draft.scenarios[1:],
    )

    save_release_draft(draft_id, draft.lock_version, changed, SHANGHAI_NOW)
    loaded = load_release_draft(draft_id)
    canonical = json.loads(compile_release_snapshot(loaded).canonical_json)
    scenario = next(item for item in canonical["scenarios"] if item["code"] == loaded.scenarios[0].code)

    assert loaded.roi_ranges["headcount"][option_code] == precise
    assert loaded.scenarios[0].efficiency == unit
    assert tuple(Decimal(value) for value in canonical["roi_ranges"]["headcount"][option_code]) == precise
    assert tuple(Decimal(value) for value in scenario["efficiency"]) == unit
    assert tuple(
        db.execute(
            "SELECT typeof(low_value),typeof(mid_value),typeof(high_value) "
            "FROM assessment_release_roi_ranges WHERE assessment_version_id=? "
            "AND option_group='headcount' AND code=?",
            (draft_id, option_code),
        ).fetchone()
    ) == ("text", "text", "text")


def test_copy_preserves_published_question_runtime_visibility(db):
    """The release root owns draft lifecycle; legacy question visibility stays copied."""
    draft_id = _copy()
    statuses = db.execute(
        "SELECT DISTINCT status FROM assessment_questions "
        "WHERE assessment_version_id=?",
        (draft_id,),
    ).fetchall()

    assert [row["status"] for row in statuses] == ["published"]


def _copy(code="v2.1-draft"):
    return copy_active_release(code, "V2.1 草稿", "admin", SHANGHAI_NOW)


def test_initial_snapshot_is_canonical_complete_and_matches_loaded_release(db):
    """Omitting labels, report fields, or a Decimal coefficient changes the digest."""
    row = db.execute(
        "SELECT v.id,s.canonical_json,s.sha256 FROM active_assessment_version a "
        "JOIN assessment_versions v ON v.id=a.assessment_version_id "
        "JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id"
    ).fetchone()
    payload = json.loads(row["canonical_json"])
    loaded = replace(load_release_draft(row["id"]), status="draft")
    compiled = compile_release_snapshot(loaded)

    assert hashlib.sha256(row["canonical_json"].encode("utf-8")).hexdigest() == row["sha256"]
    assert compiled.canonical_json == row["canonical_json"]
    assert len(payload["industries"]) == 4
    assert len(payload["scenarios"]) == 13
    assert len(payload["services"]) == 6
    assert payload["services"][0]["support_description"]
    assert payload["services"][0]["public_disclaimer"]
    assert isinstance(payload["scenarios"][0]["efficiency"][0], str)


def test_copy_code_conflict_rolls_back_without_partial_children(db):
    """A duplicate release code must not leave a second root or child projection."""
    _copy()
    with pytest.raises(DataConflictError, match="copy conflict"):
        _copy()

    assert db.execute(
        "SELECT COUNT(*) FROM assessment_versions WHERE code='v2.1-draft'"
    ).fetchone()[0] == 1


def test_save_draft_is_atomic_and_uses_optimistic_lock(db):
    """A stale writer must not replace a newer question projection."""
    release_id = _copy()
    draft = load_release_draft(release_id)
    changed_question = replace(draft.questions[0], prompt="更新后的业务频率问题？")
    changed = replace(draft, questions=(changed_question, *draft.questions[1:]))

    assert save_release_draft(release_id, 1, changed, SHANGHAI_NOW) == 2
    with pytest.raises(DataConflictError, match="update conflict"):
        save_release_draft(release_id, 1, changed, SHANGHAI_NOW)

    saved = load_release_draft(release_id)
    assert saved.lock_version == 2
    assert saved.questions[0].prompt == "更新后的业务频率问题?"


def test_child_write_failure_rolls_back_deleted_children(db):
    """A child constraint failure after deletion must restore the whole old draft."""
    release_id = _copy()
    before = load_release_draft(release_id)
    db.execute(
        "CREATE TRIGGER fail_rule_release_service_insert "
        "BEFORE INSERT ON assessment_release_services "
        "WHEN NEW.assessment_version_id=%d "
        "BEGIN SELECT RAISE(ABORT,'injected child failure'); END" % release_id
    )
    db.commit()

    with pytest.raises(DataConflictError, match="child conflict"):
        save_release_draft(release_id, 1, before, SHANGHAI_NOW)

    after = load_release_draft(release_id)
    assert after == before


def test_snapshot_protects_root_existing_option_and_new_service_rows(db):
    """Bypassing the repository must not mutate any snapshotted release layer."""
    active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    question = db.execute(
        "SELECT id FROM assessment_questions WHERE assessment_version_id=? LIMIT 1", (active,)
    ).fetchone()[0]
    option = db.execute(
        "SELECT id FROM assessment_options WHERE question_id=? LIMIT 1", (question,)
    ).fetchone()[0]
    service = db.execute(
        "SELECT id FROM assessment_release_services WHERE assessment_version_id=? LIMIT 1", (active,)
    ).fetchone()[0]

    for statement, parameters in (
        ("UPDATE assessment_versions SET name='tampered' WHERE id=?", (active,)),
        ("UPDATE assessment_options SET label='tampered' WHERE id=?", (option,)),
        ("UPDATE assessment_release_services SET public_name='tampered' WHERE id=?", (service,)),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(statement, parameters)


def test_root_allows_only_strict_snapshot_publish_and_nonactive_archive_lifecycle(db):
    """Published roots cannot be edited and the active root cannot be archived in place."""
    old_active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version"
    ).fetchone()[0]
    release_id = _copy()
    draft = load_release_draft(release_id)
    snapshot = compile_release_snapshot(draft)
    db.execute(
        "UPDATE assessment_versions SET validated_digest=?,updated_at=? WHERE id=?",
        (snapshot.sha256, "2026-09-01 10:01:00", release_id),
    )
    db.execute(
        "INSERT INTO assessment_version_snapshots "
        "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
        "VALUES (?,?,?,?,?)",
        (release_id, snapshot.schema_version, snapshot.canonical_json, snapshot.sha256, "2026-09-01 10:01:00"),
    )
    db.execute(
        "UPDATE assessment_versions SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-01 10:02:00", "2026-09-01 10:02:00", release_id),
    )
    db.commit()
    with pytest.raises(DataConflictError, match="update conflict"):
        save_release_draft(release_id, 2, replace(draft, lock_version=2), SHANGHAI_NOW)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE assessment_versions SET status='archived',updated_at=?,"
            "lock_version=lock_version+1 WHERE id=?",
            ("2026-09-01 10:03:00", old_active),
        )

    db.execute(
        "UPDATE active_assessment_version SET assessment_version_id=?,updated_at=? "
        "WHERE singleton_id=1",
        (release_id, "2026-09-01 10:03:00"),
    )
    db.execute(
        "UPDATE assessment_versions SET status='archived',updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-01 10:04:00", old_active),
    )
    assert db.execute(
        "SELECT status FROM assessment_versions WHERE id=?", (old_active,)
    ).fetchone()[0] == "archived"


def test_only_initial_v2_gets_unsnapshotted_published_digest_backfill(db):
    """An ordinary published root cannot use the one-time V2 migration exception."""
    release_id = db.execute(
        "INSERT INTO assessment_versions "
        "(code,name,status,created_at,published_at,updated_at) "
        "VALUES ('ordinary-published','ordinary','published',?,?,?)",
        ("2026-09-01 09:00:00", "2026-09-01 09:00:00", "2026-09-01 09:00:00"),
    ).lastrowid
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE assessment_versions SET validated_digest=?,updated_at=? WHERE id=?",
            ("0" * 64, "2026-09-01 09:01:00", release_id),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("DELETE FROM assessment_versions WHERE id=?", (release_id,))


def test_active_pointer_rejects_unsnapshotted_draft(db):
    """The singleton pointer cannot activate a mutable or uncompiled release."""
    release_id = _copy()
    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "UPDATE active_assessment_version SET assessment_version_id=? WHERE singleton_id=1",
            (release_id,),
        )


def test_project_connection_registers_real_utf8_sha256(db):
    """SQL integrity checks must hash the actual UTF-8 canonical bytes."""
    value = "规则发布/中文/🙂"

    assert db.execute("SELECT sha256_utf8(?)", (value,)).fetchone()[0] == hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def test_direct_snapshot_insert_rejects_forged_bytes_digest_and_cross_root(db):
    """Stored root digests cannot bless forged bytes or a snapshot from another root."""
    first_id = _copy("v2-forgery-a")
    first = compile_release_snapshot(load_release_draft(first_id))
    second_id = _copy("v2-forgery-b")
    second = compile_release_snapshot(load_release_draft(second_id))

    cases = (
        (first_id, first.canonical_json + " ", first.sha256),
        (first_id, first.canonical_json, "0" * 64),
        (second_id, first.canonical_json, first.sha256),
    )
    for release_id, canonical_json, digest in cases:
        db.execute(
            "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
            (digest, release_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="invalid"):
            db.execute(
                "INSERT INTO assessment_version_snapshots "
                "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
                "VALUES (?,?,?,?,?)",
                (release_id, "2.0", canonical_json, digest, "2026-09-01 10:02:00"),
            )

    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (second.sha256, second_id),
    )


def test_direct_snapshot_insert_rejects_real_sha_for_structurally_empty_canonical(db):
    """A genuine digest must not bless a schema/root-only canonical shell."""
    release_id = _copy("v2-empty-canonical")
    draft = load_release_draft(release_id)
    payload = {
        "schema_version": "2.0",
        "release": {
            "code": draft.code,
            "name": draft.name,
            "pain_selection": {
                "minimum": draft.pain_min_selections,
                "maximum": draft.pain_max_selections,
            },
        },
        "industries": [],
        "company_sizes": [],
        "questions": [],
        "branch_weights": {},
        "benchmarks": [],
        "roi_ranges": {},
        "public_labels": {},
        "scenarios": [],
        "services": [],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (digest, release_id),
    )

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "INSERT INTO assessment_version_snapshots "
            "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
            "VALUES (?,?,?,?,?)",
            (release_id, "2.0", canonical, digest, "2026-09-01 10:02:00"),
        )


def test_direct_publish_rejects_release_without_verified_snapshot(db):
    release_id = _copy("v2-no-snapshot")

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "UPDATE assessment_versions SET status='published',published_at=?,updated_at=? "
            "WHERE id=?",
            ("2026-09-01 10:02:00", "2026-09-01 10:02:00", release_id),
        )


def test_unsnapshotted_draft_cannot_transition_to_archived(db):
    release_id = _copy("v2-no-snapshot-archive")

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "UPDATE assessment_versions SET status='archived',updated_at=? WHERE id=?",
            ("2026-09-01 10:02:00", release_id),
        )


@pytest.mark.parametrize("target_status", ("draft", "published"))
def test_archived_release_cannot_reenter_lifecycle(db, target_status):
    active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version"
    ).fetchone()[0]
    release_id = _copy(f"v2-archive-terminal-{target_status}")
    snapshot = compile_release_snapshot(load_release_draft(release_id))
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (snapshot.sha256, release_id),
    )
    db.execute(
        "INSERT INTO assessment_version_snapshots "
        "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
        "VALUES (?,?,?,?,?)",
        (release_id, "2.0", snapshot.canonical_json, snapshot.sha256, "2026-09-01 10:02:00"),
    )
    db.execute(
        "UPDATE assessment_versions SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-01 10:03:00", "2026-09-01 10:03:00", release_id),
    )
    db.execute(
        "UPDATE active_assessment_version SET assessment_version_id=?,updated_at=? "
        "WHERE singleton_id=1",
        (release_id, "2026-09-01 10:04:00"),
    )
    db.execute(
        "UPDATE assessment_versions SET status='archived',updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-01 10:05:00", active),
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE assessment_versions SET status=?,updated_at=?,"
            "lock_version=lock_version+1 WHERE id=?",
            (target_status, "2026-09-01 10:06:00", active),
        )


def test_publish_and_active_pointer_recheck_snapshot_bytes(db):
    """Direct SQL transitions must fail closed even after snapshot rows are tampered."""
    release_id = _copy("v2-tampered-transition")
    snapshot = compile_release_snapshot(load_release_draft(release_id))
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (snapshot.sha256, release_id),
    )
    db.execute(
        "INSERT INTO assessment_version_snapshots "
        "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
        "VALUES (?,?,?,?,?)",
        (release_id, "2.0", snapshot.canonical_json, snapshot.sha256, "2026-09-01 10:02:00"),
    )
    db.execute("DROP TRIGGER prevent_assessment_snapshot_update")
    db.execute(
        "UPDATE assessment_version_snapshots SET canonical_json=canonical_json || ' ' "
        "WHERE assessment_version_id=?",
        (release_id,),
    )

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "UPDATE assessment_versions SET status='published',published_at=?,updated_at=?,"
            "lock_version=lock_version+1 "
            "WHERE id=?",
            ("2026-09-01 10:03:00", "2026-09-01 10:03:00", release_id),
        )

    db.execute("DROP TRIGGER protect_snapshotted_assessment_version_update")
    db.execute("DROP TRIGGER validate_assessment_version_publish")
    db.execute(
        "UPDATE assessment_versions SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 "
        "WHERE id=?",
        ("2026-09-01 10:03:00", "2026-09-01 10:03:00", release_id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "UPDATE active_assessment_version SET assessment_version_id=? WHERE singleton_id=1",
            (release_id,),
        )


def test_active_pointer_cannot_be_deleted(db):
    """The singleton authority cannot silently disappear outside a valid switch."""
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM active_assessment_version WHERE singleton_id=1")


def test_repeated_startup_recomputes_active_snapshot_digest(db):
    """A matching stored digest is insufficient if canonical snapshot bytes differ."""
    db.execute("DROP TRIGGER prevent_assessment_snapshot_update")
    db.execute(
        "UPDATE assessment_version_snapshots SET canonical_json=canonical_json || ' '"
    )
    db.commit()

    with pytest.raises(RuntimeError, match="invalid"):
        models.init_db()


def test_draft_children_cannot_be_reparented_into_snapshotted_release(db):
    """Checking only OLD ownership would let UPDATE bypass immutable INSERT gates."""
    active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version"
    ).fetchone()[0]
    draft_id = _copy()
    service = db.execute(
        "SELECT id FROM assessment_release_services WHERE assessment_version_id=? LIMIT 1",
        (draft_id,),
    ).fetchone()[0]
    question = db.execute(
        "SELECT id FROM assessment_questions WHERE assessment_version_id=? LIMIT 1",
        (draft_id,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE assessment_release_services "
            "SET assessment_version_id=?,code='injected_service',sort_order=99 WHERE id=?",
            (active, service),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE assessment_questions "
            "SET assessment_version_id=?,code='injected_question',sort_order=99 WHERE id=?",
            (active, question),
        )


def test_descendant_version_column_must_match_its_actual_parent(db):
    """A forged version column must not detach immutable ownership from the parent."""
    first = _copy("v2.1-first")
    second = _copy("v2.1-second")
    deliverable = db.execute(
        "SELECT id FROM assessment_release_service_deliverables "
        "WHERE assessment_version_id=? LIMIT 1",
        (first,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "UPDATE assessment_release_service_deliverables "
            "SET assessment_version_id=? WHERE id=?",
            (second, deliverable),
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda draft: replace(draft, code=True), "release_code"),
        (lambda draft: replace(draft, pain_min_selections=True), "pain_selection"),
        (
            lambda draft: replace(
                draft,
                services=(replace(draft.services[0], min_budget=Decimal("NaN")), *draft.services[1:]),
            ),
            "service_budget",
        ),
        (
            lambda draft: replace(
                draft,
                questions=(replace(draft.questions[0], prompt="联系 13800138000"), *draft.questions[1:]),
            ),
            "question",
        ),
        (
            lambda draft: replace(
                draft,
                scenarios=(replace(draft.scenarios[0], service_code="missing_service"), *draft.scenarios[1:]),
            ),
            "scenario_service_reference",
        ),
        (
            lambda draft: replace(
                draft,
                services=(
                    replace(draft.services[0], deliverables=list(draft.services[0].deliverables)),
                    *draft.services[1:],
                ),
            ),
            "service_content",
        ),
    ],
)
def test_pure_validation_rejects_exact_types_nonfinite_pii_and_cross_refs(db, mutation, error):
    """Weak type coercion or contact-shaped draft copy must fail before persistence."""
    draft = load_release_draft(_copy())
    assert error in validate_release_draft(mutation(draft))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda draft: replace(draft, industries=[*draft.industries]),
        lambda draft: replace(draft, industries=(object(),)),
        lambda draft: replace(draft, questions=(object(),)),
        lambda draft: replace(
            draft,
            questions=(replace(draft.questions[0], options=[*draft.questions[0].options]),)
            + draft.questions[1:],
        ),
        lambda draft: replace(draft, branch_weights=[]),
        lambda draft: replace(draft, branch_weights={"manufacturing": []}),
        lambda draft: replace(draft, scenarios=(object(),)),
        lambda draft: replace(draft, services=(object(),)),
        lambda draft: replace(
            draft,
            scenarios=(replace(draft.scenarios[0], department_links=(object(),)),)
            + draft.scenarios[1:],
        ),
        lambda draft: replace(
            draft,
            public_labels=replace(draft.public_labels, dimensions=[]),
        ),
    ),
)
def test_malformed_nested_shapes_return_stable_errors_without_throwing(db, mutation):
    draft = load_release_draft(_copy("v2-malformed-shape"))
    malformed = mutation(draft)

    first = validate_release_draft(malformed)
    second = validate_release_draft(malformed)

    assert type(first) is tuple
    assert first
    assert second == first


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (
            lambda draft: replace(
                draft,
                industries=(replace(draft.industries[0], label="联系 138 0013 8000"),)
                + draft.industries[1:],
            ),
            "industries",
        ),
        (
            lambda draft: replace(
                draft,
                questions=(replace(draft.questions[0], prompt="邮箱 ｔｅｓｔ＠ｅｘａｍｐｌｅ．ｃｏｍ"),)
                + draft.questions[1:],
            ),
            "question",
        ),
        (
            lambda draft: replace(
                draft,
                scenarios=(replace(draft.scenarios[0], description="座机 010-12345678"),)
                + draft.scenarios[1:],
            ),
            "scenario_identity",
        ),
        (
            lambda draft: replace(
                draft,
                services=(
                    replace(
                        draft.services[0],
                        deliverables=("微信号: Zhang_San88",) + draft.services[0].deliverables[1:],
                    ),
                )
                + draft.services[1:],
            ),
            "service_content",
        ),
        (
            lambda draft: replace(
                draft,
                public_labels=replace(
                    draft.public_labels,
                    dimensions={
                        **draft.public_labels.dimensions,
                        "business_value": "wechat: contact88",
                    },
                ),
            ),
            "dimension_labels",
        ),
    ),
)
def test_nfkc_and_formatted_contact_pii_is_rejected_across_public_copy(
    db, mutation, error
):
    draft = load_release_draft(_copy("v2-pii-shapes"))
    assert error in validate_release_draft(mutation(draft))


def test_save_normalizes_all_public_copy_and_rejects_duplicate_text_relations(db):
    draft_id = _copy("v2-normalized-copy")
    draft = load_release_draft(draft_id)
    service = draft.services[0]
    normalized = replace(
        draft,
        services=(replace(service, public_name="ＡＩ\u3000服务"),) + draft.services[1:],
    )

    save_release_draft(draft_id, draft.lock_version, normalized, SHANGHAI_NOW)
    loaded = load_release_draft(draft_id)
    assert loaded.services[0].public_name == "AI 服务"

    duplicated = replace(
        loaded,
        services=(
            replace(
                loaded.services[0],
                deliverables=(loaded.services[0].deliverables[0],) * 2,
            ),
        )
        + loaded.services[1:],
    )
    assert "service_content" in validate_release_draft(duplicated)


def test_nfkc_collision_is_rejected_by_validate_compile_and_save(db):
    draft_id = _copy("v2-normalization-collision")
    before = load_release_draft(draft_id)
    service = before.services[0]
    collided = replace(
        before,
        services=(
            replace(service, deliverables=("ABC", "ＡＢＣ", *service.deliverables[2:])),
            *before.services[1:],
        ),
    )

    assert "service_content" in validate_release_draft(collided)
    with pytest.raises(ValueError, match="service_content"):
        compile_release_snapshot(collided)
    with pytest.raises(ValueError, match="service_content"):
        save_release_draft(draft_id, before.lock_version, collided, SHANGHAI_NOW)
    assert load_release_draft(draft_id) == before


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (
            lambda draft: replace(
                draft,
                questions=(
                    replace(
                        draft.questions[0],
                        options=(
                            replace(draft.questions[0].options[0], score=False),
                            *draft.questions[0].options[1:],
                        ),
                    ),
                    *draft.questions[1:],
                ),
            ),
            "question_options",
        ),
        (
            lambda draft: replace(
                draft,
                questions=(
                    replace(
                        draft.questions[0],
                        options=(
                            replace(draft.questions[0].options[0], sort_order=True),
                            *draft.questions[0].options[1:],
                        ),
                    ),
                    *draft.questions[1:],
                ),
            ),
            "question_options",
        ),
        (
            lambda draft: replace(
                draft,
                services=(replace(draft.services[0], sort_order=True), *draft.services[1:]),
            ),
            "services",
        ),
        (
            lambda draft: replace(
                draft,
                scenarios=(replace(draft.scenarios[0], sort_order=True), *draft.scenarios[1:]),
            ),
            "scenarios",
        ),
        (
            lambda draft: replace(
                draft,
                scenarios=(
                    replace(
                        draft.scenarios[0],
                        department_links=(
                            replace(draft.scenarios[0].department_links[0], sort_order=True),
                            *draft.scenarios[0].department_links[1:],
                        ),
                    ),
                    *draft.scenarios[1:],
                ),
            ),
            "scenario_links",
        ),
    ),
)
def test_nested_integer_fields_reject_bool(db, mutation, error):
    draft = load_release_draft(_copy("v2-bool-integer"))
    assert error in validate_release_draft(mutation(draft))


def test_canonical_validator_rejects_bool_as_question_score(db):
    release_id = _copy("v2-canonical-bool")
    snapshot = compile_release_snapshot(load_release_draft(release_id))
    payload = json.loads(snapshot.canonical_json)
    payload["questions"][0]["options"][0]["score"] = False
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (digest, release_id),
    )

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "INSERT INTO assessment_version_snapshots "
            "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
            "VALUES (?,?,?,?,?)",
            (release_id, "2.0", canonical, digest, "2026-09-01 10:02:00"),
        )


def test_canonical_validator_rejects_noncanonical_nfkc_collision(db):
    release_id = _copy("v2-canonical-nfkc-collision")
    snapshot = compile_release_snapshot(load_release_draft(release_id))
    payload = json.loads(snapshot.canonical_json)
    payload["services"][0]["deliverables"][:2] = ["ABC", "ＡＢＣ"]
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (digest, release_id),
    )

    with pytest.raises(sqlite3.IntegrityError, match="invalid"):
        db.execute(
            "INSERT INTO assessment_version_snapshots "
            "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
            "VALUES (?,?,?,?,?)",
            (release_id, "2.0", canonical, digest, "2026-09-01 10:02:00"),
        )


@pytest.mark.parametrize(
    "table",
    ("assessment_release_departments", "assessment_release_pain_points"),
)
@pytest.mark.parametrize("operation", ("insert", "update"))
def test_release_dictionary_branch_must_match_industry_owner(db, table, operation):
    release_id = _copy(f"v2-owner-{table[-4:]}-{operation}")
    owners = {
        row["code"]: row["id"]
        for row in db.execute(
            "SELECT id,code FROM assessment_release_industries "
            "WHERE assessment_version_id=? AND code IN ('retail','manufacturing')",
            (release_id,),
        )
    }
    code = f"ownership_probe_{operation}"
    if operation == "insert":
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute(
                f"INSERT INTO {table} "
                "(assessment_version_id,industry_id,branch_code,code,label,sort_order) "
                "VALUES (?,?,?,?,?,999)",
                (release_id, owners["retail"], "manufacturing", code, "归属探针"),
            )
    else:
        row_id = db.execute(
            f"INSERT INTO {table} "
            "(assessment_version_id,industry_id,branch_code,code,label,sort_order) "
            "VALUES (?,?,?,?,?,999)",
            (release_id, owners["retail"], "retail", code, "归属探针"),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute(
                f"UPDATE {table} SET branch_code='manufacturing' WHERE id=?",
                (row_id,),
            )


@pytest.mark.parametrize(
    "value",
    (
        "请联系 (010) 12345678",
        "手机 138.0013.8000",
        "邮箱 用户@例子.公司",
        "全国热线 400-180-3358",
        "座机 010-1234-5678",
        "座机 (010) 1234 5678",
        "座机 +86 (010) 1234-5678",
    ),
)
def test_shared_public_text_gate_rejects_extended_nfkc_contact_shapes(value):
    assert _text(value, 500) is False


def test_query_rule_releases_uses_shared_page_contract_and_clamps_high_page(db):
    """Admin list ordering and high-page behavior must match the Task 15 contract."""
    _copy("v2.1-a")
    _copy("v2.1-b")
    page = query_rule_releases(RuleReleaseFilters(status="draft"), PageRequest(999, 20))

    assert page.page == 1
    assert page.total == 2
    assert tuple(item.code for item in page.items) == ("v2.1-b", "v2.1-a")


def test_repeated_startup_keeps_existing_draft_and_snapshot_bytes(db):
    """Startup reconciliation must no-op even when future drafts already exist."""
    release_id = _copy()
    before_snapshot = db.execute(
        "SELECT canonical_json FROM assessment_version_snapshots"
    ).fetchone()[0]
    before = load_release_draft(release_id)

    models.init_db()

    assert load_release_draft(release_id) == before
    assert db.execute(
        "SELECT canonical_json FROM assessment_version_snapshots"
    ).fetchone()[0] == before_snapshot
