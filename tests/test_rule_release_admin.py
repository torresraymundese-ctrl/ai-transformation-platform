"""Admin rule-release editing and real-pipeline preview contracts."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import hashlib
from itertools import product
import json
import sqlite3

from bs4 import BeautifulSoup
import pytest
from werkzeug.datastructures import MultiDict

import models
import assessment_repository
from assessment.contracts import AssessmentProfile
from assessment.scoring import DIMENSION_ORDER, score_assessment
from assessment_repository import REPORT_SNAPSHOT_KEYS
from assessment_validation import BRANCH_CODES
from content_clock import shanghai_now
from rule_release_repository import (
    copy_active_release,
    load_release_draft,
    save_release_draft,
)


TOKEN = "test-csrf-token"


def _copy(code="v2.1-admin-draft", name="V2.1 管理草稿"):
    return copy_active_release(code, name, "test-admin", shanghai_now())


def test_rule_release_list_requires_authentication(client):
    assert client.get("/admin/rules").status_code == 302


def test_rule_release_list_is_private_safe_and_read_only(admin_client, db):
    first = _copy("v2.1-list-a", "列表 A")
    second = _copy("v2.1-list-b", "列表 B")
    before = db.total_changes

    response = admin_client.get("/admin/rules?status=unknown&page=999&per_page=999")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert db.total_changes == before
    soup = BeautifulSoup(response.data, "html.parser")
    rows = [row["data-release-id"] for row in soup.select("tbody tr[data-release-id]")]
    assert rows[:2] == [str(second), str(first)]
    assert soup.select_one('select[name="status"] option[selected]')["value"] == ""
    assert soup.select_one('select[name="per_page"] option[selected]')["value"] == "20"


def test_rule_release_list_exact_status_pagination_and_query_preservation(
    admin_client, db
):
    for index in range(52):
        _copy(f"v2.1-page-{index:02d}", f"分页 {index:02d}")

    response = admin_client.get("/admin/rules?status=draft&page=999&per_page=50")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert len(soup.select("tbody tr[data-release-id]")) == 2
    assert soup.select_one('[data-page-current]').get_text(strip=True) == "2 / 2"
    previous = soup.select_one('a[data-page="previous"]')["href"]
    assert "status=draft" in previous
    assert "per_page=50" in previous
    assert "page=1" in previous


def _published_archived_and_draft_release_ids(db):
    from rule_release_validation import compile_release_snapshot

    archived_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    published_id = _copy("v2.1-get-published")
    published = load_release_draft(published_id)
    snapshot = compile_release_snapshot(published)
    db.execute(
        "UPDATE assessment_versions SET validated_digest=?,updated_at=? WHERE id=?",
        (snapshot.sha256, "2026-09-02 10:01:00", published_id),
    )
    db.execute(
        "INSERT INTO assessment_version_snapshots "
        "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
        "VALUES (?,?,?,?,?)",
        (
            published_id,
            snapshot.schema_version,
            snapshot.canonical_json,
            snapshot.sha256,
            "2026-09-02 10:01:00",
        ),
    )
    db.execute(
        "UPDATE assessment_versions SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-02 10:02:00", "2026-09-02 10:02:00", published_id),
    )
    db.execute(
        "UPDATE active_assessment_version SET assessment_version_id=?,updated_at=? "
        "WHERE singleton_id=1",
        (published_id, "2026-09-02 10:03:00"),
    )
    db.execute(
        "UPDATE assessment_versions SET status='archived',updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-09-02 10:04:00", archived_id),
    )
    db.commit()
    draft_id = _copy("v2.1-get-draft")
    return published_id, archived_id, draft_id


def test_all_rule_release_get_paths_are_full_domain_read_only(admin_client, db):
    published_id, archived_id, draft_id = _published_archived_and_draft_release_ids(db)
    urls = (
        "/admin/rules",
        "/admin/rules?status=draft&page=1&per_page=20",
        "/admin/rules?status=invalid&page=-7&per_page=999",
        "/admin/rules?status=draft&status=archived&page=abc&per_page=50",
        f"/admin/rules/{draft_id}",
        f"/admin/rules/{published_id}",
        f"/admin/rules/{archived_id}",
    )
    audit_count = db.execute("SELECT COUNT(*) FROM admin_audit_logs").fetchone()[0]

    for url in urls:
        before = _domain_state(db)
        response = admin_client.get(url)

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert _domain_state(db) == before
        assert db.execute("SELECT COUNT(*) FROM admin_audit_logs").fetchone()[0] == audit_count


def _preview_request(draft, branch_code=None, level=3):
    from rule_release_service import PreviewRequest

    industry = next(
        item
        for item in draft.industries
        if item.code == (branch_code or draft.industries[0].code)
    )
    return PreviewRequest(
        branch_code=industry.code,
        subbranch_code=industry.subbranches[0].code,
        department_code=industry.departments[0].code,
        company_size_code=draft.company_sizes[0].code,
        pain_codes=(industry.pain_points[0].code,),
        answers={question.code: f"level_{level}" for question in draft.questions},
        roi_choices={
            group: next(iter(options)) for group, options in draft.roi_ranges.items()
        },
    )


def _domain_state(db):
    tables = tuple(
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        if row["name"] not in {"admin_audit_logs", "sqlite_sequence"}
    )
    state = {}
    for table in tables:
        columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
        rows = [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        state[table] = hashlib.sha256(
            json.dumps(
                {"columns": columns, "rows": rows},
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    return state


def test_preview_runs_real_pipeline_and_keeps_all_domains_unchanged(db):
    from rule_release_service import ReleasePreview, preview_release

    release_id = _copy("v2.1-real-preview")
    draft = load_release_draft(release_id)
    request = _preview_request(draft)
    before = _domain_state(db)

    preview = preview_release(release_id, request)

    assert type(preview) is ReleasePreview
    assert set(preview.report_snapshot) == REPORT_SNAPSHOT_KEYS
    assert preview.report_snapshot["rule_version"] == draft.code
    assert preview.scores["overall_score"] == 100
    assert tuple(preview.recommendations) == tuple(
        preview.report_snapshot["recommendations"]
    )
    assert json.loads(json.dumps(preview.public_config, ensure_ascii=False)) == dict(
        preview.public_config
    )
    assert _domain_state(db) == before


@pytest.mark.parametrize("branch_code", sorted(BRANCH_CODES))
def test_preview_accepts_each_release_owned_branch_and_complete_services(db, branch_code):
    from rule_release_service import preview_release

    release_id = _copy(f"v2.1-preview-{branch_code}")
    draft = load_release_draft(release_id)
    preview = preview_release(release_id, _preview_request(draft, branch_code))

    assert preview.public_config["branch"]["code"] == branch_code
    assert 1 <= len(preview.recommendations) <= 3
    for recommendation in preview.recommendations:
        package = recommendation["package"]
        assert package["deliverables"]
        assert package["implementation_steps"]
        assert package["prerequisites"]
        assert package["not_included"]
        assert package["acceptance"]


def test_preview_rejects_partial_draft_and_unknown_profile_codes(db):
    from rule_release_service import PreviewRequest, preview_release

    release_id = _copy("v2.1-invalid-preview")
    draft = load_release_draft(release_id)
    question = db.execute(
        "SELECT id FROM assessment_questions WHERE assessment_version_id=? "
        "ORDER BY sort_order LIMIT 1",
        (release_id,),
    ).fetchone()[0]
    db.execute(
        "UPDATE assessment_options SET score=9 WHERE question_id=? AND sort_order=1",
        (question,),
    )
    db.commit()
    with pytest.raises(ValueError, match="invalid"):
        preview_release(release_id, _preview_request(draft))

    clean_id = _copy("v2.1-invalid-member")
    clean = load_release_draft(clean_id)
    request = _preview_request(clean)
    unknown = replace(request, department_code="arbitrary_new_domain")
    with pytest.raises(ValueError, match="invalid"):
        preview_release(clean_id, unknown)

    with pytest.raises(TypeError):
        PreviewRequest(
            branch_code=request.branch_code,
            subbranch_code=request.subbranch_code,
            department_code=request.department_code,
            company_size_code=request.company_size_code,
            pain_codes=list(request.pain_codes),
            answers=request.answers,
            roi_choices=request.roi_choices,
        )


@pytest.mark.parametrize("branch_code", sorted(BRANCH_CODES))
def test_unchanged_copy_has_4096_score_profile_parity_with_published_catalog(
    db, branch_code
):
    from rule_release_service import _draft_catalog

    release_id = _copy(f"v2.1-score-parity-{branch_code}")
    draft = load_release_draft(release_id)
    published = assessment_repository.load_catalog(db, branch_code)
    copied = _draft_catalog(draft, branch_code)
    industry = next(item for item in draft.industries if item.code == branch_code)

    for levels in product(range(4), repeat=6):
        answer_by_dimension = dict(zip(DIMENSION_ORDER, levels))
        answers = {
            question.code: f"level_{answer_by_dimension[question.dimension]}"
            for question in draft.questions
        }
        profile = AssessmentProfile(
            branch_code=branch_code,
            subbranch_code=industry.subbranches[0].code,
            department_code=industry.departments[0].code,
            company_size_code=draft.company_sizes[0].code,
            pain_codes=(industry.pain_points[0].code,),
            answers=answers,
            roi_choices={
                group: next(iter(options))
                for group, options in draft.roi_ranges.items()
            },
        )
        assert score_assessment(copied, profile) == score_assessment(published, profile)


def test_draft_risk_copy_is_used_without_mutating_reporting_globals(db):
    from assessment.reporting import RISK_EXPLANATIONS
    from rule_release_service import preview_release

    release_id = _copy("v2.1-risk-copy")
    draft = load_release_draft(release_id)
    selected = preview_release(
        release_id, _preview_request(draft, "manufacturing")
    )
    risk_code = selected.recommendations[0]["risks"][0]["code"]
    labels = draft.public_labels
    risk_explanations = dict(labels.risk_explanations)
    custom = "草稿专属风险解释，不含联系信息。"
    risk_explanations[risk_code] = custom
    changed = replace(
        draft,
        public_labels=replace(labels, risk_explanations=risk_explanations),
    )
    save_release_draft(release_id, draft.lock_version, changed, shanghai_now())
    persisted = load_release_draft(release_id)
    normalized_custom = persisted.public_labels.risk_explanations[risk_code]

    preview = preview_release(release_id, _preview_request(persisted, "manufacturing"))

    assert normalized_custom in json.dumps(preview.report_snapshot, ensure_ascii=False)
    assert RISK_EXPLANATIONS[risk_code] != normalized_custom


def test_preview_preserves_exact_choices_and_uses_foundation_only_as_fallback(db):
    from rule_release_service import preview_release

    release_id = _copy("v2.1-boundaries")
    draft = load_release_draft(release_id)
    low_request = _preview_request(draft, "manufacturing", level=0)
    low = preview_release(release_id, low_request)
    high = preview_release(
        release_id, _preview_request(draft, "manufacturing", level=3)
    )

    assert low.recommendations[0]["scenario"]["code"] == "data_process_foundation"
    assert high.recommendations[0]["scenario"]["code"] != "data_process_foundation"
    assert low.report_snapshot["assessment"]["answers"] == dict(low_request.answers)
    assert low.report_snapshot["assessment"]["roi_choices"] == dict(
        low_request.roi_choices
    )


@pytest.mark.parametrize("mapping_name", ("answers", "roi_choices"))
@pytest.mark.parametrize("malformation", ("missing", "extra", "wrong_value"))
def test_preview_rejects_non_exact_choice_mappings(mapping_name, malformation, db):
    from rule_release_service import preview_release

    release_id = _copy(f"v2.1-exact-{mapping_name}-{malformation}")
    draft = load_release_draft(release_id)
    request = _preview_request(draft)
    changed = dict(getattr(request, mapping_name))
    if malformation == "missing":
        changed.pop(next(iter(changed)))
    elif malformation == "extra":
        changed["arbitrary_new_domain"] = "level_0"
    else:
        changed[next(iter(changed))] = "arbitrary_new_domain"

    with pytest.raises(ValueError, match="invalid"):
        preview_release(release_id, replace(request, **{mapping_name: changed}))


def test_every_scenario_minimum_score_has_exact_minus_equal_plus_boundary(db):
    from assessment.contracts import ScoreResult
    from assessment.matching import match_scenarios
    from rule_release_service import _draft_scenarios, _draft_services

    release_id = _copy("v2.1-every-threshold")
    draft = load_release_draft(release_id)
    services = tuple(replace(service, category="pilot") for service in _draft_services(draft))
    checked = set()

    for release_scenario in draft.scenarios:
        if release_scenario.fallback_only:
            continue
        branch_code = release_scenario.department_links[0].branch_code
        runtime = _draft_scenarios(draft, branch_code)
        foundation = next(
            scenario for scenario in runtime if scenario.code == "data_process_foundation"
        )
        target = replace(
            next(scenario for scenario in runtime if scenario.code == release_scenario.code),
            integration_level="low",
        )
        industry = next(item for item in draft.industries if item.code == branch_code)
        profile = AssessmentProfile(
            branch_code=branch_code,
            subbranch_code=industry.subbranches[0].code,
            department_code=target.department_codes[0],
            company_size_code=draft.company_sizes[0].code,
            pain_codes=(
                target.pain_codes[0]
                if target.pain_codes
                else industry.pain_points[0].code,
            ),
            answers={"delivery_timeline": "level_3"},
            roi_choices={"budget": target.budget_codes[0]},
        )
        for dimension, threshold in target.minimum_scores.items():
            for delta, expected_code in (
                (-1, "data_process_foundation"),
                (0, target.code),
                (1, target.code),
            ):
                dimensions = {code: 100 for code in DIMENSION_ORDER}
                dimensions[dimension] = threshold + delta
                scores = ScoreResult(
                    dimension_scores=dimensions,
                    overall_score=100,
                    maturity_code="collaborate",
                    strongest_dimension="business_value",
                    weakest_dimension=dimension,
                )

                matches = match_scenarios(
                    profile, scores, (target, foundation), services
                )

                assert matches[0].scenario.code == expected_code
                checked.add((target.code, dimension, threshold, delta))

    assert {scenario.code for scenario in draft.scenarios if not scenario.fallback_only} == {
        item[0] for item in checked
    }


def _edit_form(draft, **overrides):
    values = [
        ("csrf_token", TOKEN),
        ("expected_lock_version", str(draft.lock_version)),
        ("name", draft.name),
        ("pain_min_selections", str(draft.pain_min_selections)),
        ("pain_max_selections", str(draft.pain_max_selections)),
    ]
    for industry in draft.industries:
        prefix = f"industry__{industry.code}__"
        values.extend(
            (
                (prefix + "label", industry.label),
                (prefix + "position", str(industry.sort_order)),
            )
        )
        for collection, family in (
            ("subbranches", "subbranch"),
            ("departments", "department"),
            ("pain_points", "pain"),
        ):
            for item in getattr(industry, collection):
                item_prefix = prefix + f"{family}__{item.code}__"
                values.extend(
                    (
                        (item_prefix + "label", item.label),
                        (item_prefix + "position", str(item.sort_order)),
                    )
                )
    for item in draft.company_sizes:
        prefix = f"company_size__{item.code}__"
        values.extend(
            ((prefix + "label", item.label), (prefix + "position", str(item.sort_order)))
        )
    values.extend(
        (f"public__risk_explanations__{code}", text)
        for code, text in draft.public_labels.risk_explanations.items()
    )
    for family in (
        "risk_labels",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
    ):
        values.extend(
            (f"public__{family}__{code}", text)
            for code, text in getattr(draft.public_labels, family).items()
        )
    for group, labels in draft.public_labels.roi_options.items():
        values.extend(
            (f"public__roi_options__{group}__{code}", text)
            for code, text in labels.items()
        )
    for question in draft.questions:
        prefix = f"question__{question.code}__"
        values.extend(
            (
                (prefix + "dimension", question.dimension),
                (prefix + "prompt", question.prompt),
                (prefix + "position", str(question.sort_order)),
            )
        )
        for option in question.options:
            option_prefix = prefix + f"option__{option.code}__"
            values.extend(
                (
                    (option_prefix + "label", option.label),
                    (option_prefix + "score", str(option.score)),
                    (option_prefix + "position", str(option.sort_order)),
                )
            )
    for branch_code, weights in draft.branch_weights.items():
        values.extend(
            (f"weight__{branch_code}__{dimension}", str(value))
            for dimension, value in weights.items()
        )
    for benchmark in draft.benchmarks:
        values.append((f"benchmark__{benchmark.branch_code}__label", benchmark.label))
        values.extend(
            (f"benchmark__{benchmark.branch_code}__{dimension}", str(value))
            for dimension, value in benchmark.scores.items()
        )
    for group, options in draft.roi_ranges.items():
        for code, triple in options.items():
            values.extend(
                (f"roi__{group}__{code}__{band}", str(value))
                for band, value in zip(("low", "mid", "high"), triple)
            )
    for scenario in draft.scenarios:
        prefix = f"scenario__{scenario.code}__"
        values.extend(
            (prefix + "minimum__" + dimension, str(score))
            for dimension, score in scenario.minimum_scores.items()
        )
        values.extend(
            (
                (prefix + "integration_level", scenario.integration_level),
                (prefix + "service_code", scenario.service_code),
                (prefix + "category_code", scenario.category_code),
                (prefix + "public_name", scenario.public_name),
                (prefix + "description", scenario.description),
                (prefix + "min_weeks", str(scenario.min_weeks)),
                (prefix + "max_weeks", str(scenario.max_weeks)),
                (prefix + "position", str(scenario.sort_order)),
            )
        )
        for name in ("efficiency", "loss_improvement", "annual_support_rate"):
            values.extend(
                (prefix + f"{name}__{index}", str(value))
                for index, value in enumerate(getattr(scenario, name))
            )
        for name, choices in (
            ("branches", scenario.branch_codes),
            (
                "departments",
                tuple(f"{item.branch_code}:{item.code}" for item in scenario.department_links),
            ),
            (
                "pains",
                tuple(f"{item.branch_code}:{item.code}" for item in scenario.pain_links),
            ),
            ("budgets", scenario.budget_codes),
            ("risks", scenario.risk_codes),
        ):
            values.extend((prefix + name, value) for value in choices)
    for service in draft.services:
        prefix = f"service__{service.code}__"
        values.extend(
            (
                (prefix + "category", service.category),
                (prefix + "public_name", service.public_name),
                (prefix + "min_budget", str(service.min_budget)),
                (prefix + "max_budget", str(service.max_budget)),
                (prefix + "min_weeks", str(service.min_weeks)),
                (prefix + "max_weeks", str(service.max_weeks)),
                (prefix + "deliverables", "\n".join(service.deliverables)),
                (
                    prefix + "implementation_steps",
                    "\n".join(service.implementation_steps),
                ),
                (prefix + "prerequisites", "\n".join(service.prerequisites)),
                (prefix + "not_included", "\n".join(service.not_included)),
                (prefix + "acceptance", "\n".join(service.acceptance)),
                (prefix + "support_days", str(service.support_days)),
                (prefix + "support_description", service.support_description),
                (prefix + "public_disclaimer", service.public_disclaimer),
                (prefix + "position", str(service.sort_order)),
            )
        )
    data = MultiDict(values)
    for key, value in overrides.items():
        data[key] = str(value)
    return data


def _preview_form(draft, branch="manufacturing", level=3):
    request = _preview_request(draft, branch, level)
    values = [
        ("csrf_token", TOKEN),
        ("branch_code", request.branch_code),
        ("subbranch_code", request.subbranch_code),
        ("department_code", request.department_code),
        ("company_size_code", request.company_size_code),
    ]
    values.extend(("pain_codes", code) for code in request.pain_codes)
    values.extend((f"answer__{code}", value) for code, value in request.answers.items())
    values.extend((f"roi__{group}", value) for group, value in request.roi_choices.items())
    return MultiDict(values)


def test_copy_is_csrf_audited_and_fails_closed_on_unknown_or_multivalue(
    admin_client, db
):
    assert admin_client.post(
        "/admin/rules/copy", data={"code": "v2.1-no-csrf", "name": "拒绝"}
    ).status_code == 403
    assert admin_client.post(
        "/admin/rules/copy",
        data={
            "csrf_token": TOKEN,
            "code": "v2.1-unknown",
            "name": "拒绝",
            "unexpected": "value",
        },
    ).status_code == 400
    duplicated = MultiDict(
        [
            ("csrf_token", TOKEN),
            ("code", "v2.1-one"),
            ("code", "v2.1-two"),
            ("name", "拒绝"),
        ]
    )
    assert admin_client.post("/admin/rules/copy", data=duplicated).status_code == 400

    response = admin_client.post(
        "/admin/rules/copy",
        data={"csrf_token": TOKEN, "code": "v2.1-http-copy", "name": "HTTP 草稿"},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/admin/rules/2")
    audit = db.execute(
        "SELECT action,status_code FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(audit) == ("admin_rule_copy", 303)


def test_edit_page_is_choice_first_and_published_release_is_read_only(
    admin_client, db
):
    release_id = _copy("v2.1-choice-first")
    draft = load_release_draft(release_id)
    before = db.total_changes
    response = admin_client.get(f"/admin/rules/{release_id}")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert db.total_changes == before
    assert draft.code in soup.get_text()
    assert soup.select_one('form[data-rule-edit] input[name="expected_lock_version"]')
    assert soup.select_one('select[name$="__service_code"]')
    assert soup.select_one('select[multiple][name$="__branches"]')
    assert soup.select_one('[data-reorder="scenarios"] select[name$="__position"]')
    assert soup.select_one('select[name^="question__"][name$="__score"]')
    assert soup.select_one('input[name^="weight__"]')
    assert soup.select_one('input[name^="benchmark__"]')
    assert soup.select_one('input[name^="roi__"]')
    assert soup.select_one('textarea[name^="service__"][name$="__deliverables"]')
    assert soup.select_one('input[name^="public__dimensions__"]')
    assert soup.select_one('[data-compiled-digest]')

    published_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    published = admin_client.get(f"/admin/rules/{published_id}")
    assert published.status_code == 200
    assert not BeautifulSoup(published.data, "html.parser").select("form[data-rule-edit]")
    assert admin_client.post(
        f"/admin/rules/{published_id}", data={"csrf_token": TOKEN}
    ).status_code == 409


def test_edit_template_escapes_release_owned_text_without_inline_json(admin_client):
    release_id = _copy("v2.1-escaped-copy", "<script>alert(1)</script>")

    response = admin_client.get(f"/admin/rules/{release_id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "application/json" not in body


def test_edit_success_increments_lock_and_conflict_preserves_submitted_values(
    admin_client
):
    release_id = _copy("v2.1-edit-lock")
    draft = load_release_draft(release_id)
    response = admin_client.post(
        f"/admin/rules/{release_id}", data=_edit_form(draft, name="已保存名称")
    )
    assert response.status_code == 303
    saved = load_release_draft(release_id)
    assert saved.lock_version == draft.lock_version + 1
    assert saved.name == "已保存名称"

    stale_form = _edit_form(saved, name="冲突时保留我")
    save_release_draft(
        release_id,
        saved.lock_version,
        replace(saved, name="另一位管理员已保存"),
        shanghai_now(),
    )
    conflict = admin_client.post(f"/admin/rules/{release_id}", data=stale_form)
    assert conflict.status_code == 409
    soup = BeautifulSoup(conflict.data, "html.parser")
    assert soup.select_one('input[name="name"]')["value"] == "冲突时保留我"
    assert "更新冲突" in soup.get_text()


def test_http_edit_persists_full_rule_surfaces_and_explicit_positions(
    admin_client
):
    release_id = _copy("v2.1-full-editor")
    draft = load_release_draft(release_id)
    first_scenario, second_scenario = draft.scenarios[:2]
    first_service, second_service = draft.services[:2]
    branch = next(iter(draft.branch_weights))
    benchmark = next(item for item in draft.benchmarks if item.branch_code == branch)
    group = "headcount"
    option = next(iter(draft.roi_ranges[group]))
    service_prefix = f"service__{first_service.code}__"
    data = _edit_form(draft)
    data[f"weight__{branch}__business_value"] = str(
        draft.branch_weights[branch]["business_value"] + 1
    )
    data[f"weight__{branch}__process"] = str(
        draft.branch_weights[branch]["process"] - 1
    )
    data[f"benchmark__{branch}__label"] = "管理员修改后的基准线"
    data[f"benchmark__{branch}__data"] = str(benchmark.scores["data"] + 1)
    precise = (
        "12345678901234567890.1234567890123456789012345678901",
        "12345678901234567890.2234567890123456789012345678901",
        "9.999999999999999999999999999999999999999E+900",
    )
    for band, value in zip(("low", "mid", "high"), precise):
        data[f"roi__{group}__{option}__{band}"] = value
    service_updates = {
        "category": first_service.category,
        "public_name": "完整编辑服务包",
        "min_budget": "12345.67890123456789",
        "max_budget": "98765.67890123456789",
        "min_weeks": "2",
        "max_weeks": "9",
        "deliverables": "交付物甲\n交付物乙",
        "implementation_steps": "步骤甲\n步骤乙",
        "prerequisites": "前提甲\n前提乙",
        "not_included": "不包含甲\n不包含乙",
        "acceptance": "验收甲\n验收乙",
        "support_days": "45",
        "support_description": "支持说明已更新",
        "public_disclaimer": "公开声明已更新",
    }
    for name, value in service_updates.items():
        data[service_prefix + name] = value
    data["public__dimensions__data"] = "数据基础（编辑后）"
    data[f"scenario__{first_scenario.code}__position"] = "2"
    data[f"scenario__{second_scenario.code}__position"] = "1"
    data[f"service__{first_service.code}__position"] = "2"
    data[f"service__{second_service.code}__position"] = "1"

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 303
    saved = load_release_draft(release_id)
    assert saved.branch_weights[branch]["business_value"] == draft.branch_weights[branch]["business_value"] + 1
    assert saved.branch_weights[branch]["process"] == draft.branch_weights[branch]["process"] - 1
    saved_benchmark = next(item for item in saved.benchmarks if item.branch_code == branch)
    assert saved_benchmark.label == "管理员修改后的基准线"
    assert saved_benchmark.scores["data"] == benchmark.scores["data"] + 1
    assert saved.roi_ranges[group][option] == tuple(Decimal(value) for value in precise)
    saved_service = next(item for item in saved.services if item.code == first_service.code)
    assert saved_service.public_name == "完整编辑服务包"
    assert saved_service.min_budget == Decimal("12345.67890123456789")
    assert saved_service.max_budget == Decimal("98765.67890123456789")
    assert saved_service.deliverables == ("交付物甲", "交付物乙")
    assert saved_service.implementation_steps == ("步骤甲", "步骤乙")
    assert saved_service.prerequisites == ("前提甲", "前提乙")
    assert saved_service.not_included == ("不包含甲", "不包含乙")
    assert saved_service.acceptance == ("验收甲", "验收乙")
    assert saved_service.support_days == 45
    assert saved_service.support_description == "支持说明已更新"
    assert saved_service.public_disclaimer == "公开声明已更新"
    assert saved.public_labels.dimensions["data"] == "数据基础(编辑后)"
    assert tuple(item.code for item in saved.scenarios[:2]) == (
        second_scenario.code,
        first_scenario.code,
    )
    assert tuple(item.code for item in saved.services[:2]) == (
        second_service.code,
        first_service.code,
    )
    html = BeautifulSoup(
        admin_client.get(f"/admin/rules/{release_id}").data, "html.parser"
    )
    assert [item["data-scenario-code"] for item in html.select("[data-scenario-code]")[:2]] == [
        second_scenario.code,
        first_scenario.code,
    ]
    assert [item["data-service-code"] for item in html.select("[data-service-code]")[:2]] == [
        second_service.code,
        first_service.code,
    ]


def _swap_first_two_positions(data, family, items):
    first, second = items[:2]
    data[f"{family}__{first.code}__position"] = "2"
    data[f"{family}__{second.code}__position"] = "1"


def _swap_items(items):
    return (
        replace(items[1], sort_order=1),
        replace(items[0], sort_order=2),
        *items[2:],
    )


def _reordered_owned_draft(draft):
    industries = tuple(
        replace(
            industry,
            subbranches=_swap_items(industry.subbranches),
            departments=_swap_items(industry.departments),
            pain_points=_swap_items(industry.pain_points),
        )
        for industry in draft.industries
    )
    questions = tuple(
        replace(question, options=_swap_items(question.options))
        for question in draft.questions
    )
    return replace(
        draft,
        industries=_swap_items(industries),
        company_sizes=_swap_items(draft.company_sizes),
        questions=_swap_items(questions),
    )


def test_http_edit_persists_all_release_owned_labels_and_nested_orders(
    admin_client, db
):
    from rule_release_service import _draft_catalog, _draft_public_config, preview_release
    from rule_release_validation import (
        compile_release_snapshot,
        validate_canonical_release_json,
        validate_release_draft,
    )

    release_id = _copy("v2.1-owned-label-order")
    draft = load_release_draft(release_id)
    original_snapshot = compile_release_snapshot(draft)
    data = _edit_form(draft)
    expected_labels = {}
    _swap_first_two_positions(data, "industry", draft.industries)
    for industry_index, industry in enumerate(draft.industries, 1):
        industry_label = f"编辑行业{industry_index}"
        data[f"industry__{industry.code}__label"] = industry_label
        expected_labels[("industry", industry.code)] = industry_label
        for collection, family, label_prefix in (
            (industry.subbranches, "subbranch", "细分支"),
            (industry.departments, "department", "部门"),
            (industry.pain_points, "pain", "痛点"),
        ):
            _swap_first_two_positions(
                data, f"industry__{industry.code}__{family}", collection
            )
            for item_index, item in enumerate(collection, 1):
                label = f"{label_prefix}{industry_index}-{item_index}"
                data[
                    f"industry__{industry.code}__{family}__{item.code}__label"
                ] = label
                expected_labels[(family, industry.code, item.code)] = label
    _swap_first_two_positions(data, "company_size", draft.company_sizes)
    for index, item in enumerate(draft.company_sizes, 1):
        label = f"企业规模{index}"
        data[f"company_size__{item.code}__label"] = label
        expected_labels[("company_size", item.code)] = label
    _swap_first_two_positions(data, "question", draft.questions)
    for question_index, question in enumerate(draft.questions, 1):
        _swap_first_two_positions(
            data, f"question__{question.code}__option", question.options
        )
        for option_index, option in enumerate(question.options, 1):
            label = f"选项{question_index}-{option_index}"
            data[
                f"question__{question.code}__option__{option.code}__label"
            ] = label
            expected_labels[("option", question.code, option.code)] = label

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 303
    saved = load_release_draft(release_id)
    assert validate_release_draft(saved) == ()
    assert tuple(item.code for item in saved.industries[:2]) == tuple(
        item.code for item in reversed(draft.industries[:2])
    )
    assert tuple(item.code for item in saved.company_sizes[:2]) == tuple(
        item.code for item in reversed(draft.company_sizes[:2])
    )
    assert tuple(item.code for item in saved.questions[:2]) == tuple(
        item.code for item in reversed(draft.questions[:2])
    )
    for industry in saved.industries:
        assert industry.label == expected_labels[("industry", industry.code)]
        original = next(item for item in draft.industries if item.code == industry.code)
        for collection, original_collection, family in (
            (industry.subbranches, original.subbranches, "subbranch"),
            (industry.departments, original.departments, "department"),
            (industry.pain_points, original.pain_points, "pain"),
        ):
            assert tuple(item.code for item in collection[:2]) == tuple(
                item.code for item in reversed(original_collection[:2])
            )
            assert all(
                item.label == expected_labels[(family, industry.code, item.code)]
                for item in collection
            )
    assert all(
        item.label == expected_labels[("company_size", item.code)]
        for item in saved.company_sizes
    )
    for question in saved.questions:
        original = next(item for item in draft.questions if item.code == question.code)
        assert tuple(item.code for item in question.options[:2]) == tuple(
            item.code for item in reversed(original.options[:2])
        )
        assert all(
            option.label == expected_labels[("option", question.code, option.code)]
            for option in question.options
        )

    html = BeautifulSoup(
        admin_client.get(f"/admin/rules/{release_id}").data, "html.parser"
    )
    assert [item["data-industry-code"] for item in html.select("[data-industry-code]")] == [
        item.code for item in saved.industries
    ]
    assert [item["data-company-size-code"] for item in html.select("[data-company-size-code]")] == [
        item.code for item in saved.company_sizes
    ]
    assert [item["data-question-code"] for item in html.select("[data-question-code]")] == [
        item.code for item in saved.questions
    ]
    for industry in saved.industries:
        fieldset = html.select_one(f'[data-industry-code="{industry.code}"]')
        for attribute, collection in (
            ("data-subbranch-code", industry.subbranches),
            ("data-department-code", industry.departments),
            ("data-pain-code", industry.pain_points),
        ):
            assert [item[attribute] for item in fieldset.select(f"[{attribute}]")] == [
                item.code for item in collection
            ]
    for question in saved.questions:
        fieldset = html.select_one(f'[data-question-code="{question.code}"]')
        assert [item["data-option-code"] for item in fieldset.select("[data-option-code]")] == [
            item.code for item in question.options
        ]

    for industry in saved.industries:
        config = _draft_public_config(saved, _draft_catalog(saved, industry.code), industry.code)
        benchmark = next(
            item for item in saved.benchmarks if item.branch_code == industry.code
        )
        expected = {
            "branch": {"code": industry.code, "label": industry.label},
            "subbranches": [
                {"code": item.code, "label": item.label}
                for item in industry.subbranches
            ],
            "departments": [
                {"code": item.code, "label": item.label}
                for item in industry.departments
            ],
            "pain_points": [
                {"code": item.code, "label": item.label}
                for item in industry.pain_points
            ],
            "company_sizes": [
                {"code": item.code, "label": item.label}
                for item in saved.company_sizes
            ],
            "pain_selection": {
                "minimum": saved.pain_min_selections,
                "maximum": saved.pain_max_selections,
            },
            "roi_options": {
                group: list(options) for group, options in saved.roi_ranges.items()
            },
            "reference_label": benchmark.label,
        }
        compact = lambda value: json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        assert compact(config) == compact(expected)

    snapshot = compile_release_snapshot(saved)
    canonical = json.loads(snapshot.canonical_json)
    assert snapshot.sha256 == hashlib.sha256(
        snapshot.canonical_json.encode("utf-8")
    ).hexdigest()
    assert snapshot.sha256 != original_snapshot.sha256
    assert [item["code"] for item in canonical["industries"]] == [
        item.code for item in saved.industries
    ]
    assert [item["code"] for item in canonical["company_sizes"]] == [
        item.code for item in saved.company_sizes
    ]
    assert [item["code"] for item in canonical["questions"]] == [
        item.code for item in saved.questions
    ]
    assert validate_canonical_release_json(
        snapshot.canonical_json,
        saved.code,
        saved.name,
        saved.pain_min_selections,
        saved.pain_max_selections,
    )
    assert db.execute(
        "SELECT canonical_release_valid(?,?,?,?,?)",
        (
            snapshot.canonical_json,
            saved.code,
            saved.name,
            saved.pain_min_selections,
            saved.pain_max_selections,
        ),
    ).fetchone()[0] == 1
    preview = preview_release(release_id, _preview_request(saved, "manufacturing"))
    assert preview.report_snapshot["rule_version"] == saved.code
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (snapshot.sha256, release_id),
    )
    db.execute(
        "INSERT INTO assessment_version_snapshots "
        "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
        "VALUES (?,?,?,?,?)",
        (
            release_id,
            snapshot.schema_version,
            snapshot.canonical_json,
            snapshot.sha256,
            "2026-09-02 11:00:00",
        ),
    )
    assert db.execute(
        "SELECT sha256 FROM assessment_version_snapshots WHERE assessment_version_id=?",
        (release_id,),
    ).fetchone()[0] == snapshot.sha256


@pytest.mark.parametrize("branch_code", sorted(BRANCH_CODES))
def test_reordered_questions_and_options_keep_all_4096_scores_identical(
    db, branch_code
):
    from rule_release_service import _draft_catalog
    from rule_release_validation import compile_release_snapshot, validate_release_draft

    release_id = _copy(f"v2.1-reorder-parity-{branch_code}")
    draft = load_release_draft(release_id)
    reordered = _reordered_owned_draft(draft)
    assert validate_release_draft(reordered) == ()
    compile_release_snapshot(reordered)
    original_catalog = _draft_catalog(draft, branch_code)
    reordered_catalog = _draft_catalog(reordered, branch_code)
    industry = next(item for item in draft.industries if item.code == branch_code)

    for levels in product(range(4), repeat=6):
        answer_by_dimension = dict(zip(DIMENSION_ORDER, levels))
        answers = {
            question.code: f"level_{answer_by_dimension[question.dimension]}"
            for question in draft.questions
        }
        profile = AssessmentProfile(
            branch_code=branch_code,
            subbranch_code=industry.subbranches[0].code,
            department_code=industry.departments[0].code,
            company_size_code=draft.company_sizes[0].code,
            pain_codes=(industry.pain_points[0].code,),
            answers=answers,
            roi_choices={
                group: next(iter(options))
                for group, options in draft.roi_ranges.items()
            },
        )
        assert score_assessment(reordered_catalog, profile) == score_assessment(
            original_catalog, profile
        )


def test_http_edit_allows_balanced_cross_dimension_relation_swap(
    admin_client, db
):
    from rule_release_service import preview_release
    from rule_release_validation import (
        compile_release_snapshot,
        validate_canonical_release_json,
        validate_release_draft,
    )

    release_id = _copy("v2.1-balanced-dimension-swap")
    draft = load_release_draft(release_id)
    business_question = next(
        item for item in draft.questions if item.dimension == "business_value"
    )
    process_question = next(
        item for item in draft.questions if item.dimension == "process"
    )
    data = _edit_form(draft)
    data[f"question__{business_question.code}__dimension"] = "process"
    data[f"question__{process_question.code}__dimension"] = "business_value"

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 303
    saved = load_release_draft(release_id)
    assert validate_release_draft(saved) == ()
    assert next(
        item for item in saved.questions if item.code == business_question.code
    ).dimension == "process"
    assert next(
        item for item in saved.questions if item.code == process_question.code
    ).dimension == "business_value"
    snapshot = compile_release_snapshot(saved)
    assert validate_canonical_release_json(
        snapshot.canonical_json,
        saved.code,
        saved.name,
        saved.pain_min_selections,
        saved.pain_max_selections,
    )
    assert db.execute(
        "SELECT canonical_release_valid(?,?,?,?,?)",
        (
            snapshot.canonical_json,
            saved.code,
            saved.name,
            saved.pain_min_selections,
            saved.pain_max_selections,
        ),
    ).fetchone()[0] == 1
    request = _preview_request(saved, "manufacturing", level=0)
    answers = dict(request.answers)
    answers[business_question.code] = "level_3"
    preview = preview_release(release_id, replace(request, answers=answers))

    assert preview.scores["dimension_scores"]["business_value"] == 0
    assert preview.scores["dimension_scores"]["process"] == 50
    assert preview.report_snapshot["scores"] == dict(preview.scores)


@pytest.mark.parametrize(
    "malformation",
    (
        "company_code",
        "company_sort",
        "question_code",
        "question_sort",
        "dimension_unknown",
        "dimension_imbalance",
        "option_code",
        "option_sort",
        "score",
    ),
)
def test_reordered_release_owned_identity_stays_fail_closed(db, malformation):
    from rule_release_validation import validate_release_draft

    release_id = _copy(f"v2.1-owned-bad-{malformation}")
    draft = _reordered_owned_draft(load_release_draft(release_id))
    if malformation == "company_code":
        items = list(draft.company_sizes)
        items[0] = replace(items[0], code="arbitrary_new_domain")
        draft = replace(draft, company_sizes=tuple(items))
    elif malformation == "company_sort":
        items = list(draft.company_sizes)
        items[0] = replace(items[0], sort_order=2)
        draft = replace(draft, company_sizes=tuple(items))
    elif malformation == "question_code":
        items = list(draft.questions)
        items[0] = replace(items[0], code="arbitrary_new_domain")
        draft = replace(draft, questions=tuple(items))
    elif malformation == "question_sort":
        items = list(draft.questions)
        items[0] = replace(items[0], sort_order=2)
        draft = replace(draft, questions=tuple(items))
    elif malformation == "dimension_unknown":
        items = list(draft.questions)
        items[0] = replace(items[0], dimension="arbitrary_new_domain")
        draft = replace(draft, questions=tuple(items))
    elif malformation == "dimension_imbalance":
        items = list(draft.questions)
        items[0] = replace(items[0], dimension="delivery")
        draft = replace(draft, questions=tuple(items))
    else:
        questions = list(draft.questions)
        options = list(questions[0].options)
        if malformation == "option_code":
            options[0] = replace(options[0], code="arbitrary_new_domain")
        elif malformation == "option_sort":
            options[0] = replace(options[0], sort_order=2)
        else:
            options[0] = replace(options[0], score=(options[0].score + 1) % 4)
        questions[0] = replace(questions[0], options=tuple(options))
        draft = replace(draft, questions=tuple(questions))

    assert validate_release_draft(draft)


@pytest.mark.parametrize(
    "malformation",
    (
        "company_code",
        "company_duplicate",
        "question_code",
        "dimension_unknown",
        "dimension_imbalance",
        "option_code",
        "score",
    ),
)
def test_canonical_udf_and_snapshot_trigger_reject_reordered_identity_forgery(
    db, malformation
):
    from rule_release_validation import compile_release_snapshot

    release_id = _copy(f"v2.1-canonical-owned-{malformation}")
    draft = _reordered_owned_draft(load_release_draft(release_id))
    snapshot = compile_release_snapshot(draft)
    payload = json.loads(snapshot.canonical_json)
    if malformation == "company_code":
        payload["company_sizes"][0]["code"] = "arbitrary_new_domain"
    elif malformation == "company_duplicate":
        payload["company_sizes"][0]["code"] = payload["company_sizes"][1]["code"]
    elif malformation == "question_code":
        payload["questions"][0]["code"] = "arbitrary_new_domain"
    elif malformation == "dimension_unknown":
        payload["questions"][0]["dimension"] = "arbitrary_new_domain"
    elif malformation == "dimension_imbalance":
        payload["questions"][0]["dimension"] = "delivery"
    elif malformation == "option_code":
        payload["questions"][0]["options"][0]["code"] = "arbitrary_new_domain"
    else:
        payload["questions"][0]["options"][0]["score"] = 3
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert db.execute(
        "SELECT canonical_release_valid(?,?,?,?,?)",
        (
            canonical,
            draft.code,
            draft.name,
            draft.pain_min_selections,
            draft.pain_max_selections,
        ),
    ).fetchone()[0] == 0
    db.execute(
        "UPDATE assessment_versions SET validated_digest=? WHERE id=?",
        (digest, release_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO assessment_version_snapshots "
            "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
            "VALUES (?,?,?,?,?)",
            (release_id, "2.0", canonical, digest, "2026-09-02 12:00:00"),
        )


def _nested_position_group(draft, family):
    if family == "industry":
        return "industry", draft.industries
    if family == "company_size":
        return "company_size", draft.company_sizes
    if family == "question":
        return "question", draft.questions
    industry = draft.industries[0]
    if family in {"subbranch", "department", "pain"}:
        collection = {
            "subbranch": industry.subbranches,
            "department": industry.departments,
            "pain": industry.pain_points,
        }[family]
        return f"industry__{industry.code}__{family}", collection
    question = draft.questions[0]
    return f"question__{question.code}__option", question.options


@pytest.mark.parametrize("problem", ("missing", "duplicate", "out_of_range"))
@pytest.mark.parametrize(
    "family",
    ("industry", "subbranch", "department", "pain", "company_size", "question", "option"),
)
def test_nested_release_positions_fail_closed_without_domain_writes(
    admin_client, db, problem, family
):
    release_id = _copy(f"v2.1-{family[:5]}-{problem}")
    draft = load_release_draft(release_id)
    position_family, items = _nested_position_group(draft, family)
    first, second = items[:2]
    data = _edit_form(draft)
    key = f"{position_family}__{first.code}__position"
    if problem == "missing":
        data.pop(key)
    elif problem == "duplicate":
        data[key] = str(second.sort_order)
    else:
        data[key] = str(len(items) + 1)
    before = _domain_state(db)

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 400
    assert "提交内容无效" in response.get_data(as_text=True)
    assert _domain_state(db) == before
    saved = load_release_draft(release_id)
    assert saved.lock_version == draft.lock_version


@pytest.mark.parametrize("problem", ("missing", "duplicate", "out_of_range"))
@pytest.mark.parametrize("collection", ("scenario", "service"))
def test_http_edit_rejects_invalid_explicit_positions_without_writes(
    admin_client, problem, collection
):
    release_id = _copy(f"v2.1-{collection}-{problem}")
    draft = load_release_draft(release_id)
    items = getattr(draft, collection + "s")
    first, second = items[:2]
    data = _edit_form(draft)
    key = f"{collection}__{first.code}__position"
    if problem == "missing":
        data.pop(key)
    elif problem == "duplicate":
        data[key] = str(second.sort_order)
    else:
        data[key] = str(len(items) + 1)

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 400
    saved = load_release_draft(release_id)
    assert saved.lock_version == draft.lock_version
    assert tuple(item.code for item in getattr(saved, collection + "s")) == tuple(
        item.code for item in items
    )


def test_edit_and_preview_reject_unknown_fields_and_render_generic_errors(
    admin_client
):
    release_id = _copy("v2.1-fail-closed")
    draft = load_release_draft(release_id)
    edit = _edit_form(draft)
    edit.add("unexpected", "secret")
    rejected = admin_client.post(f"/admin/rules/{release_id}", data=edit)
    assert rejected.status_code == 400
    assert b"unexpected" not in rejected.data

    preview = _preview_form(draft)
    preview.add("unexpected", "secret")
    rejected = admin_client.post(
        f"/admin/rules/{release_id}/preview", data=preview
    )
    assert rejected.status_code == 400
    assert b"unexpected" not in rejected.data

    duplicated = _preview_form(draft)
    duplicated.add("branch_code", "retail")
    assert admin_client.post(
        f"/admin/rules/{release_id}/preview", data=duplicated
    ).status_code == 400


@pytest.mark.parametrize("branch", sorted(BRANCH_CODES))
def test_http_preview_renders_all_sections_without_domain_writes(
    admin_client, db, branch
):
    release_id = _copy(f"v2.1-http-{branch}")
    draft = load_release_draft(release_id)
    before = _domain_state(db)
    response = admin_client.post(
        f"/admin/rules/{release_id}/preview", data=_preview_form(draft, branch)
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    soup = BeautifulSoup(response.data, "html.parser")
    assert {item["data-preview-section"] for item in soup.select("[data-preview-section]")} == {
        "scores",
        "scenarios",
        "roi",
        "roadmap",
        "services",
    }
    assert _domain_state(db) == before


@pytest.mark.parametrize("branch", sorted(BRANCH_CODES))
def test_published_public_config_adapter_matches_pure_draft_builder(db, branch):
    from rule_release_service import _draft_catalog, _draft_public_config

    release_id = db.execute(
        "SELECT assessment_version_id FROM active_assessment_version WHERE singleton_id=1"
    ).fetchone()[0]
    published = assessment_repository.load_catalog(db, branch)
    expected = assessment_repository.load_public_config(db, published, branch)
    frozen = load_release_draft(release_id)

    actual = _draft_public_config(frozen, _draft_catalog(frozen, branch), branch)

    assert actual == expected
    assert json.dumps(
        actual, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8") == json.dumps(
        expected, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def test_omitted_report_public_copy_keeps_compact_canonical_bytes(db):
    from assessment.reporting import (
        RISK_EXPLANATIONS,
        ReportPublicCopy,
        build_report_snapshot,
    )
    from assessment.roi import calculate_roi
    from assessment.matching import match_scenarios
    from assessment_validation import parse_preview_payload, validate_profile_membership
    from rule_release_service import (
        _draft_catalog,
        _draft_public_config,
        _draft_scenarios,
        _draft_services,
        _preview_payload,
    )

    release_id = _copy("v2.1-report-compat")
    draft = load_release_draft(release_id)
    request = _preview_request(draft, "manufacturing")
    catalog = _draft_catalog(draft, request.branch_code)
    public_config = _draft_public_config(draft, catalog, request.branch_code)
    profile = parse_preview_payload(_preview_payload(request))
    validate_profile_membership(profile, catalog, public_config)
    scores = score_assessment(catalog, profile)
    matches = match_scenarios(
        profile,
        scores,
        _draft_scenarios(draft, request.branch_code),
        _draft_services(draft),
    )
    roi = calculate_roi(
        profile.roi_choices,
        draft.roi_ranges,
        matches[0].scenario,
        matches[0].service,
    )

    omitted = build_report_snapshot(
        profile, scores, matches, roi, catalog, draft.roi_ranges
    )
    explicit = build_report_snapshot(
        profile,
        scores,
        matches,
        roi,
        catalog,
        draft.roi_ranges,
        public_copy=ReportPublicCopy(RISK_EXPLANATIONS),
    )

    compact = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert compact(omitted) == compact(explicit)


def test_report_public_copy_is_deeply_immutable_and_detached():
    from assessment.reporting import ReportPublicCopy

    source = {"source_quality": "初始解释"}
    public_copy = ReportPublicCopy(source)
    source["source_quality"] = "外部篡改"

    assert public_copy.risk_explanations["source_quality"] == "初始解释"
    with pytest.raises(TypeError):
        public_copy.risk_explanations["source_quality"] = "内部篡改"
    with pytest.raises(FrozenInstanceError):
        public_copy.risk_explanations = {}


@pytest.mark.parametrize("raw", ("1e-10000", "1e-999999999"))
def test_edit_rejects_decimal_fixed_point_expansion_dos_before_writes(
    admin_client, raw
):
    release_id = _copy(f"v2.1-decimal-dos-{raw[-5:]}")
    draft = load_release_draft(release_id)
    key = f"scenario__{draft.scenarios[0].code}__efficiency__0"
    data = _edit_form(draft)
    data[key] = raw

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 400
    after = load_release_draft(release_id)
    assert after.lock_version == draft.lock_version
    assert after.scenarios[0].efficiency == draft.scenarios[0].efficiency


@pytest.mark.parametrize("field", ("expected_lock_version", "scenario_min_weeks"))
def test_edit_rejects_oversized_integer_before_conversion_or_writes(
    admin_client, field
):
    release_id = _copy(f"v2.1-integer-dos-{field[:8]}")
    draft = load_release_draft(release_id)
    key = (
        "expected_lock_version"
        if field == "expected_lock_version"
        else f"scenario__{draft.scenarios[0].code}__min_weeks"
    )
    data = _edit_form(draft)
    data[key] = "9" * 5000

    response = admin_client.post(f"/admin/rules/{release_id}", data=data)

    assert response.status_code == 400
    after = load_release_draft(release_id)
    assert after.lock_version == draft.lock_version
    assert after.scenarios[0].min_weeks == draft.scenarios[0].min_weeks


def _release_with_custom_recommended_service(code):
    from rule_release_service import preview_release

    release_id = _copy(code)
    draft = load_release_draft(release_id)
    request = _preview_request(draft, "manufacturing", level=3)
    selected_code = preview_release(release_id, request).recommendations[0]["package"][
        "code"
    ]
    services = tuple(
        replace(
            service,
            public_name="<script>alert(1)</script>",
            min_budget=Decimal("12345.67890123456789"),
            max_budget=Decimal("98765.67890123456789"),
            min_weeks=2,
            max_weeks=9,
            deliverables=("预览交付物甲", "预览交付物乙"),
            implementation_steps=("预览步骤甲", "预览步骤乙"),
            prerequisites=("预览前提甲",),
            not_included=("预览不包含甲",),
            acceptance=("预览验收甲",),
            support_days=45,
            support_description="预览专属支持说明",
            public_disclaimer="预览专属公开声明",
        )
        if service.code == selected_code
        else service
        for service in draft.services
    )
    save_release_draft(
        release_id,
        draft.lock_version,
        replace(draft, services=services),
        shanghai_now(),
    )
    persisted = load_release_draft(release_id)
    return release_id, persisted, _preview_request(persisted, "manufacturing", level=3), selected_code


def test_preview_exposes_deep_immutable_full_release_service_projection(db):
    from rule_release_service import PreviewService, preview_release

    release_id, draft, request, selected_code = _release_with_custom_recommended_service(
        "v2.1-service-projection"
    )
    expected = next(item for item in draft.services if item.code == selected_code)

    preview = preview_release(release_id, request)
    detail = next(item for item in preview.services if item.code == selected_code)

    assert type(detail) is PreviewService
    for field in (
        "code",
        "category",
        "public_name",
        "min_budget",
        "max_budget",
        "min_weeks",
        "max_weeks",
        "deliverables",
        "implementation_steps",
        "prerequisites",
        "not_included",
        "acceptance",
        "support_days",
        "support_description",
        "public_disclaimer",
    ):
        assert getattr(detail, field) == getattr(expected, field)
    with pytest.raises(FrozenInstanceError):
        detail.public_name = "mutated"
    with pytest.raises(TypeError):
        detail.deliverables[0] = "mutated"
    assert "support_description" not in json.dumps(
        preview.report_snapshot, ensure_ascii=False
    )


def test_http_preview_renders_and_escapes_full_release_service_projection(
    admin_client
):
    release_id, draft, _request, selected_code = _release_with_custom_recommended_service(
        "v2.1-service-html"
    )

    response = admin_client.post(
        f"/admin/rules/{release_id}/preview",
        data=_preview_form(draft, "manufacturing", level=3),
    )
    body = response.get_data(as_text=True)
    service = BeautifulSoup(response.data, "html.parser").select_one(
        f'[data-preview-service="{selected_code}"]'
    )

    assert response.status_code == 200
    assert service is not None
    assert "预览专属支持说明" in service.get_text()
    assert "预览专属公开声明" in service.get_text()
    assert "预览交付物甲" in service.get_text()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
