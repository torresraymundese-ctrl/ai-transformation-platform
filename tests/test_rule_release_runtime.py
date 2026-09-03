"""Published rule runtime is driven only by immutable release snapshots."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import json

import pytest

from models import get_db
from repository import DataConflictError
from rule_release_repository import copy_active_release
from tests.assessment_flow_helpers import FLOW_NOW


def test_active_runtime_loader_uses_caller_connection_without_transaction_control(db):
    from rule_release_runtime import load_active_rule_bundle

    db.execute("BEGIN")
    bundle = load_active_rule_bundle(db, "manufacturing")

    assert bundle.version_id == 1
    assert bundle.version_code == "v2.0-2026-08-19"
    assert bundle.catalog.version_id == bundle.version_id
    assert bundle.public_config["branch"]["code"] == "manufacturing"
    assert len(bundle.scenarios) == 13
    assert len(bundle.services) == 6
    assert db.in_transaction is True
    db.rollback()


def test_publish_release_switches_pointer_and_archives_previous_atomically(db):
    from rule_release_service import publish_release

    release_id = copy_active_release(
        "v2.1-runtime-red",
        "Runtime RED",
        "test-admin",
        FLOW_NOW - timedelta(minutes=1),
    )
    expected_lock = db.execute(
        "SELECT lock_version FROM assessment_versions WHERE id=?", (release_id,)
    ).fetchone()[0]

    digest = publish_release(
        release_id, expected_lock, "test-admin", FLOW_NOW
    )

    active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    statuses = {
        row["id"]: row["status"]
        for row in db.execute(
            "SELECT id,status FROM assessment_versions WHERE id IN (1,?)",
            (release_id,),
        )
    }
    snapshot = db.execute(
        "SELECT sha256 FROM assessment_version_snapshots WHERE assessment_version_id=?",
        (release_id,),
    ).fetchone()[0]
    assert active == release_id
    assert statuses == {1: "archived", release_id: "published"}
    assert snapshot == digest


@pytest.mark.parametrize("damage", ("sha", "canonical", "oversize"))
def test_runtime_loader_rejects_corrupt_active_snapshot_before_leaving_transaction(
    db, damage
):
    from rule_release_runtime import RuleRuntimeError, load_active_rule_bundle

    row = db.execute(
        "SELECT s.canonical_json,s.sha256 FROM assessment_version_snapshots s "
        "WHERE s.assessment_version_id=1"
    ).fetchone()
    canonical = row["canonical_json"]
    digest = row["sha256"]
    db.execute("DROP TRIGGER prevent_assessment_snapshot_update")
    if damage == "sha":
        db.execute(
            "UPDATE assessment_version_snapshots SET sha256=? "
            "WHERE assessment_version_id=1",
            ("0" * 64,),
        )
    else:
        db.execute("DROP TRIGGER protect_snapshotted_assessment_version_update")
        if damage == "canonical":
            payload = json.loads(canonical)
            payload["questions"] = []
            damaged = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        else:
            damaged = "{" + ("x" * (1024 * 1024)) + "}"
        digest = hashlib.sha256(damaged.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE assessment_version_snapshots SET canonical_json=?,sha256=? "
            "WHERE assessment_version_id=1",
            (damaged, digest),
        )
        db.execute(
            "UPDATE assessment_versions SET validated_digest=? WHERE id=1",
            (digest,),
        )
    db.commit()

    db.execute("BEGIN")
    with pytest.raises(RuleRuntimeError, match="^rule release unavailable$"):
        load_active_rule_bundle(db, "manufacturing")
    assert db.in_transaction is True
    db.rollback()


def test_competing_publish_connections_leave_one_complete_winner_and_one_draft(db):
    from rule_release_service import publish_release

    release_ids = tuple(
        copy_active_release(
            f"v2.1-race-{index}",
            f"Race {index}",
            "test-admin",
            FLOW_NOW - timedelta(minutes=2 - index),
        )
        for index in (0, 1)
    )
    locks = {
        row["id"]: row["lock_version"]
        for row in db.execute(
            "SELECT id,lock_version FROM assessment_versions WHERE id IN (?,?)",
            release_ids,
        )
    }
    publish_times = {
        release_ids[0]: FLOW_NOW,
        release_ids[1]: FLOW_NOW + timedelta(seconds=1),
    }

    def publish(release_id):
        try:
            return (release_id, "published", publish_release(
                release_id,
                locks[release_id],
                "test-admin",
                publish_times[release_id],
            ))
        except DataConflictError:
            return (release_id, "conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, release_ids))

    assert sorted(result[1] for result in results) == ["conflict", "published"]
    active = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    statuses = {
        row["id"]: row["status"]
        for row in db.execute(
            "SELECT id,status FROM assessment_versions WHERE id IN (?,?)",
            release_ids,
        )
    }
    assert statuses[active] == "published"
    loser = next(release_id for release_id in release_ids if release_id != active)
    assert statuses[loser] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM assessment_version_snapshots "
        "WHERE assessment_version_id IN (?,?)",
        release_ids,
    ).fetchone()[0] == 1


def test_serial_publish_rejects_a_draft_copied_from_the_previous_active_release(db):
    from rule_release_service import publish_release

    first_id = copy_active_release(
        "v2.1-serial-winner",
        "Serial winner",
        "test-admin",
        FLOW_NOW - timedelta(minutes=2),
    )
    stale_id = copy_active_release(
        "v2.1-serial-stale",
        "Serial stale",
        "test-admin",
        FLOW_NOW - timedelta(minutes=1),
    )

    publish_release(first_id, 1, "test-admin", FLOW_NOW)
    with pytest.raises(DataConflictError, match="rule release publication conflict"):
        publish_release(
            stale_id,
            1,
            "test-admin",
            FLOW_NOW + timedelta(seconds=1),
        )

    assert db.execute(
        "SELECT assessment_version_id FROM active_assessment_version "
        "WHERE singleton_id=1"
    ).fetchone()[0] == first_id
    stale = db.execute(
        "SELECT status,lock_version,validated_digest,published_at "
        "FROM assessment_versions WHERE id=?",
        (stale_id,),
    ).fetchone()
    assert tuple(stale) == ("draft", 1, None, None)
    assert db.execute(
        "SELECT COUNT(*) FROM assessment_version_snapshots "
        "WHERE assessment_version_id=?",
        (stale_id,),
    ).fetchone()[0] == 0


def test_publish_audit_failure_rolls_back_snapshot_status_pointer_and_digest(
    db, monkeypatch
):
    import rule_release_service

    release_id = copy_active_release(
        "v2.1-rollback",
        "Rollback",
        "test-admin",
        FLOW_NOW - timedelta(minutes=1),
    )
    before_audits = db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0]
    monkeypatch.setattr(
        rule_release_service,
        "write_governance_audit_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        rule_release_service.publish_release(
            release_id, 1, "test-admin", FLOW_NOW
        )

    row = db.execute(
        "SELECT status,lock_version,validated_digest,published_at "
        "FROM assessment_versions WHERE id=?",
        (release_id,),
    ).fetchone()
    assert tuple(row) == ("draft", 1, None, None)
    assert db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM assessment_version_snapshots WHERE assessment_version_id=?",
        (release_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0] == before_audits


def test_direct_rule_dto_compile_and_save_reject_unbounded_decimal(db):
    from rule_release_repository import load_release_draft, save_release_draft
    from rule_release_validation import compile_release_snapshot

    release_id = copy_active_release(
        "v2.1-unbounded-dto",
        "Unbounded DTO",
        "test-admin",
        FLOW_NOW,
    )
    draft = load_release_draft(release_id)
    service = draft.services[0]
    malformed = replace(
        draft,
        services=(
            replace(service, max_budget=Decimal("1E+100000")),
            *draft.services[1:],
        ),
    )

    with pytest.raises(ValueError, match="service_budget"):
        compile_release_snapshot(malformed)
    with pytest.raises(ValueError, match="service_budget"):
        save_release_draft(
            release_id,
            draft.lock_version,
            malformed,
            FLOW_NOW + timedelta(seconds=1),
        )
    assert load_release_draft(release_id) == draft


@pytest.mark.parametrize(
    ("target", "expected_error"),
    (
        ("roi_range", "roi_ranges"),
        ("scenario_efficiency", "scenario_roi"),
        ("scenario_loss", "scenario_roi"),
        ("scenario_support", "scenario_roi"),
    ),
)
def test_rule_validation_bounds_every_decimal_family(db, target, expected_error):
    from rule_release_repository import load_release_draft
    from rule_release_validation import compile_release_snapshot

    release_id = copy_active_release(
        f"v2.1-unbounded-{target}",
        "Unbounded family",
        "test-admin",
        FLOW_NOW,
    )
    draft = load_release_draft(release_id)
    if target == "roi_range":
        roi_ranges = {
            group: dict(options) for group, options in draft.roi_ranges.items()
        }
        first_code = next(iter(roi_ranges["budget"]))
        roi_ranges["budget"][first_code] = (
            Decimal("0"),
            Decimal("1"),
            Decimal("1E+100000"),
        )
        malformed = replace(draft, roi_ranges=roi_ranges)
    else:
        field = {
            "scenario_efficiency": "efficiency",
            "scenario_loss": "loss_improvement",
            "scenario_support": "annual_support_rate",
        }[target]
        scenario = draft.scenarios[0]
        malformed_scenario = replace(
            scenario,
            **{
                field: (
                    Decimal("0"),
                    Decimal("1E-100000"),
                    getattr(scenario, field)[2],
                )
            },
        )
        malformed = replace(
            draft,
            scenarios=(malformed_scenario, *draft.scenarios[1:]),
        )

    with pytest.raises(ValueError, match=expected_error):
        compile_release_snapshot(malformed)


def test_rule_decimal_boundary_compiles_and_canonical_validator_is_bounded(db):
    from rule_release_repository import load_release_draft
    from rule_release_validation import (
        compile_release_snapshot,
        validate_canonical_release_json,
    )

    draft = load_release_draft(1)
    boundary = replace(
        draft,
        status="draft",
        services=(
            replace(draft.services[0], max_budget=Decimal("1E+900")),
            *draft.services[1:],
        ),
    )
    snapshot = compile_release_snapshot(boundary)
    assert validate_canonical_release_json(
        snapshot.canonical_json,
        boundary.code,
        boundary.name,
        boundary.pain_min_selections,
        boundary.pain_max_selections,
    )

    payload = json.loads(snapshot.canonical_json)
    payload["services"][0]["budget"][1] = "1" + "0" * 2048
    oversized_fixed = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert not validate_canonical_release_json(
        oversized_fixed,
        boundary.code,
        boundary.name,
        boundary.pain_min_selections,
        boundary.pain_max_selections,
    )


def test_canonical_validator_rejects_oversize_before_json_parse(monkeypatch):
    import rule_release_validation

    called = []
    original = rule_release_validation.json.loads

    def loads(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(rule_release_validation.json, "loads", loads)
    assert not rule_release_validation.validate_canonical_release_json(
        " " * (1024 * 1024 + 1), "v2-test", "Test", 1, 3
    )
    assert called == []


def test_canonical_validator_contains_deep_json_recursion_for_python_and_sql(db):
    from rule_release_validation import validate_canonical_release_json

    deep_json = "[" * 10_000 + "0" + "]" * 10_000
    assert not validate_canonical_release_json(
        deep_json, "v2-test", "Test", 1, 3
    )
    assert db.execute(
        "SELECT canonical_release_valid(?,?,?,?,?)",
        (deep_json, "v2-test", "Test", 1, 3),
    ).fetchone()[0] == 0


def test_direct_persisted_rule_decimal_is_rejected_before_publish_writes(db):
    from rule_release_service import publish_release

    release_id = copy_active_release(
        "v2.1-unbounded-persisted",
        "Unbounded persisted",
        "test-admin",
        FLOW_NOW,
    )
    before_audits = db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0]
    db.execute(
        "UPDATE assessment_release_services SET max_budget='1E+100000' "
        "WHERE assessment_version_id=? AND code='foundation_workshop'",
        (release_id,),
    )
    db.commit()

    with pytest.raises(ValueError, match="service_budget"):
        publish_release(
            release_id,
            1,
            "test-admin",
            FLOW_NOW + timedelta(seconds=1),
        )

    assert db.execute(
        "SELECT status,lock_version,validated_digest,published_at "
        "FROM assessment_versions WHERE id=?",
        (release_id,),
    ).fetchone()[:] == ("draft", 1, None, None)
    assert db.execute(
        "SELECT COUNT(*) FROM assessment_version_snapshots "
        "WHERE assessment_version_id=?",
        (release_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT assessment_version_id FROM active_assessment_version "
        "WHERE singleton_id=1"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0] == before_audits
