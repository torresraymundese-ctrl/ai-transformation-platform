from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier
import uuid

import models
import pytest
from bs4 import BeautifulSoup

from repository import DataConflictError


SUBMISSION_KEY_1 = "550e8400-e29b-41d4-a716-446655440000"
SUBMISSION_KEY_2 = "123e4567-e89b-42d3-a456-426614174000"
SUBMISSION_KEY_3 = "2c1f7d82-4e74-4a7a-9e36-81eb3bb07a8a"
QUESTION_CODES = (
    "business_value_frequency",
    "business_value_scope",
    "process_documentation",
    "process_stability",
    "data_availability",
    "data_quality",
    "systems_foundation",
    "systems_automation",
    "organization_owner",
    "organization_adoption",
    "delivery_budget",
    "delivery_timeline",
)


def _insert_assessment(db, *, company="测试企业", contact="测试联系人"):
    lead_id = db.execute(
        "INSERT INTO leads (company_name,contact_name) VALUES (?,?)",
        (company, contact),
    ).lastrowid
    assessment_id = db.execute(
        "INSERT INTO assessments (lead_id,submission_key,completed_at) "
        "VALUES (?,?,?)",
        (lead_id, f"assessment-{lead_id}", "2026-08-20 09:00:00"),
    ).lastrowid
    db.commit()
    return assessment_id, lead_id


def _complete_assessment(client, *, submission_key=None, phone="13800138000"):
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@example.invalid",
        PRIVACY_POLICY_URL="https://example.invalid/privacy",
    )
    config = client.get("/api/v2/assessment/config/manufacturing")
    assert config.status_code == 200
    csrf_token = config.get_json()["csrf_token"]
    completion = client.post(
        "/api/v2/assessment/complete",
        json={
            "submission_key": submission_key or str(uuid.uuid4()),
            "assessment": {
                "schema_version": "2.0",
                "profile": {
                    "branch_code": "manufacturing",
                    "subbranch_code": "discrete_manufacturing",
                    "department_code": "production",
                    "company_size_code": "50_200",
                    "pain_codes": ["production_reporting"],
                },
                "answers": {code: "level_3" for code in QUESTION_CODES},
                "roi_choices": {
                    "headcount": "6_20",
                    "monthly_hours": "20_80",
                    "monthly_cost": "8000_15000",
                    "loss_factor": "normal",
                    "budget": "50000_200000",
                },
            },
            "contact": {
                "company_name": "预约接口测试企业",
                "contact_name": "测试联系人",
                "phone": phone,
            },
            "consent": {
                "accepted": True,
                "policy_version": "2026-08-19",
            },
            "attribution": {"source": "website_assessment"},
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert completion.status_code == 200
    return completion.get_json()["assessment_id"], csrf_token


def _valid_api_payload(assessment_id, *, submission_key=SUBMISSION_KEY_1):
    return {
        "assessment_id": assessment_id,
        "submission_key": submission_key,
        "preferred_date": "2026-08-20",
        "time_slot": "afternoon",
        "note": "  希望先讨论客服场景  ",
    }


def _use_shanghai_test_clock(client):
    client.application.config["APPOINTMENT_NOW_PROVIDER"] = lambda: datetime(
        2026, 8, 19, 16, 30, tzinfo=timezone.utc
    )


def test_create_appointment_derives_lead_and_starts_pending(client):
    from appointment_repository import create_appointment

    db = models.get_db()
    try:
        assessment_id, lead_id = _insert_assessment(db)

        appointment_id = create_appointment(
            db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "希望先讨论客服场景",
        )

        appointment = db.execute(
            "SELECT * FROM appointments WHERE id=?", (appointment_id,)
        ).fetchone()
        assert appointment["assessment_id"] == assessment_id
        assert appointment["lead_id"] == lead_id
        assert appointment["preferred_date"] == "2026-08-25"
        assert appointment["time_slot"] == "afternoon"
        assert appointment["note"] == "希望先讨论客服场景"
        assert appointment["status"] == "pending"
    finally:
        db.close()


def test_same_assessment_key_returns_original_current_appointment(client):
    from appointment_repository import create_appointment, get_appointment

    db = models.get_db()
    try:
        assessment_id, _ = _insert_assessment(db)
        original_id = create_appointment(
            db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "原始备注",
        )
        db.execute(
            "UPDATE appointments SET status='confirmed' WHERE id=?",
            (original_id,),
        )
        db.commit()

        replay_id = create_appointment(
            db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 9, 1),
            "morning",
            "重放不应覆盖",
        )

        appointment = get_appointment(db, replay_id)
        assert replay_id == original_id
        assert appointment["status"] == "confirmed"
        assert appointment["preferred_date"] == "2026-08-25"
        assert appointment["time_slot"] == "afternoon"
        assert appointment["note"] == "原始备注"
        assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
    finally:
        db.close()


def test_cross_assessment_key_replay_is_generic_conflict_and_rolls_back(client):
    from appointment_repository import create_appointment

    db = models.get_db()
    try:
        first_assessment, lead_id = _insert_assessment(db)
        second_assessment = db.execute(
            "INSERT INTO assessments (lead_id,submission_key,completed_at) "
            "VALUES (?,?,?)",
            (lead_id, "assessment-second", "2026-08-20 09:05:00"),
        ).lastrowid
        db.commit()
        original_id = create_appointment(
            db,
            first_assessment,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "",
        )

        with pytest.raises(DataConflictError, match="appointment conflict"):
            create_appointment(
                db,
                second_assessment,
                SUBMISSION_KEY_1,
                date(2026, 8, 26),
                "evening",
                "",
            )

        assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
        assert create_appointment(
            db,
            second_assessment,
            SUBMISSION_KEY_2,
            date(2026, 8, 26),
            "evening",
            "",
        ) != original_id
    finally:
        db.close()


def test_two_connections_serialize_same_key_creation_without_duplicate(client):
    from appointment_repository import create_appointment

    setup_db = models.get_db()
    try:
        assessment_id, _ = _insert_assessment(setup_db)
    finally:
        setup_db.close()
    start = Barrier(2)

    def create_from_independent_connection():
        db = models.get_db()
        try:
            connection_identity = id(db)
            start.wait(timeout=5)
            appointment_id = create_appointment(
                db,
                assessment_id,
                SUBMISSION_KEY_1,
                date(2026, 8, 25),
                "afternoon",
                "并发幂等",
            )
            return connection_identity, appointment_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(create_from_independent_connection) for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    assert len({connection_id for connection_id, _ in results}) == 2
    assert len({appointment_id for _, appointment_id in results}) == 1
    db = models.get_db()
    try:
        rows = db.execute(
            "SELECT id,status,preferred_date,time_slot,note FROM appointments"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (results[0][1], "pending", "2026-08-25", "afternoon", "并发幂等")
        ]
        assert db.execute(
            "SELECT COUNT(*) FROM analytics_events "
            "WHERE assessment_id=? AND event_name='appointment_submitted'",
            (assessment_id,),
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_two_connections_cas_same_transition_to_one_write_and_one_conflict(client):
    from appointment_repository import create_appointment, transition_appointment

    setup_db = models.get_db()
    try:
        assessment_id, _ = _insert_assessment(setup_db)
        appointment_id = create_appointment(
            setup_db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "",
        )
    finally:
        setup_db.close()
    start = Barrier(2)

    def confirm_from_independent_connection():
        db = models.get_db()
        try:
            connection_identity = id(db)
            start.wait(timeout=5)
            try:
                transition_appointment(db, appointment_id, "confirmed")
                outcome = "confirmed"
            except DataConflictError as error:
                assert str(error) == "appointment transition conflict"
                outcome = "conflict"
            return connection_identity, outcome
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm_from_independent_connection) for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    assert len({connection_id for connection_id, _ in results}) == 2
    assert sorted(outcome for _, outcome in results) == ["confirmed", "conflict"]
    db = models.get_db()
    try:
        appointment = db.execute(
            "SELECT status,confirmed_at,completed_at,cancelled_at "
            "FROM appointments WHERE id=?",
            (appointment_id,),
        ).fetchone()
        assert appointment["status"] == "confirmed"
        assert appointment["confirmed_at"]
        assert appointment["completed_at"] is None
        assert appointment["cancelled_at"] is None
    finally:
        db.close()


@pytest.mark.parametrize(
    ("start_status", "new_status", "timestamp_column"),
    (
        ("pending", "confirmed", "confirmed_at"),
        ("pending", "cancelled", "cancelled_at"),
        ("confirmed", "completed", "completed_at"),
        ("confirmed", "cancelled", "cancelled_at"),
    ),
)
def test_transition_appointment_allows_only_forward_workflow_edges(
    client, start_status, new_status, timestamp_column
):
    from appointment_repository import create_appointment, transition_appointment

    db = models.get_db()
    try:
        assessment_id, _ = _insert_assessment(db)
        appointment_id = create_appointment(
            db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "",
        )
        if start_status == "confirmed":
            db.execute(
                "UPDATE appointments SET status='confirmed',"
                "confirmed_at='2026-08-21 09:00:00' WHERE id=?",
                (appointment_id,),
            )
            db.commit()

        assert transition_appointment(db, appointment_id, new_status) is None

        appointment = db.execute(
            "SELECT * FROM appointments WHERE id=?", (appointment_id,)
        ).fetchone()
        assert appointment["status"] == new_status
        assert appointment[timestamp_column]
    finally:
        db.close()


@pytest.mark.parametrize(
    ("start_status", "new_status"),
    (
        ("pending", "pending"),
        ("confirmed", "confirmed"),
        ("completed", "cancelled"),
        ("cancelled", "confirmed"),
        ("pending", "completed"),
        ("confirmed", "pending"),
        ("pending", "unknown"),
        ("pending", ["confirmed"]),
    ),
)
def test_invalid_or_same_status_transition_is_deterministic_without_write(
    client, start_status, new_status
):
    from appointment_repository import create_appointment, transition_appointment

    db = models.get_db()
    try:
        assessment_id, _ = _insert_assessment(db)
        appointment_id = create_appointment(
            db,
            assessment_id,
            SUBMISSION_KEY_1,
            date(2026, 8, 25),
            "afternoon",
            "",
        )
        db.execute(
            "UPDATE appointments SET status=?,updated_at='2026-08-20 09:00:00' "
            "WHERE id=?",
            (start_status, appointment_id),
        )
        db.commit()
        before = dict(
            db.execute(
                "SELECT * FROM appointments WHERE id=?", (appointment_id,)
            ).fetchone()
        )

        with pytest.raises(
            DataConflictError, match="appointment transition conflict"
        ):
            transition_appointment(db, appointment_id, new_status)

        after = dict(
            db.execute(
                "SELECT * FROM appointments WHERE id=?", (appointment_id,)
            ).fetchone()
        )
        assert after == before
    finally:
        db.close()


def test_authorized_api_creates_pending_intent_with_exact_public_response(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    payload = _valid_api_payload(assessment_id)
    payload["note"] = f"  {'字' * 500}  "

    response = client.post(
        "/api/v2/appointments",
        json=payload,
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"success", "appointment_id", "status"}
    assert body["success"] is True
    assert body["status"] == "pending"
    db = models.get_db()
    try:
        appointment = db.execute(
            "SELECT * FROM appointments WHERE id=?", (body["appointment_id"],)
        ).fetchone()
        assessment = db.execute(
            "SELECT lead_id FROM assessments WHERE id=?", (assessment_id,)
        ).fetchone()
        assert appointment["assessment_id"] == assessment_id
        assert appointment["lead_id"] == assessment["lead_id"]
        assert appointment["preferred_date"] == "2026-08-20"
        assert appointment["time_slot"] == "afternoon"
        assert appointment["note"] == "字" * 500
        assert appointment["status"] == "pending"
    finally:
        db.close()


def _appointment_quota_count():
    db = models.get_db()
    try:
        return db.execute(
            "SELECT COALESCE(SUM(request_count),0) FROM request_rate_limits "
            "WHERE bucket='assessment_v2_appointment'"
        ).fetchone()[0]
    finally:
        db.close()


def _appointment_count():
    db = models.get_db()
    try:
        return db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    finally:
        db.close()


def test_csrf_session_and_shape_rejections_do_not_consume_appointment_quota(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    payload = _valid_api_payload(assessment_id)

    without_csrf = client.post("/api/v2/appointments", json=payload)

    other_client = client.application.test_client()
    other_config = other_client.get("/api/v2/assessment/config/manufacturing")
    other_csrf = other_config.get_json()["csrf_token"]
    other_session = other_client.post(
        "/api/v2/appointments",
        json=payload,
        headers={"X-CSRF-Token": other_csrf},
    )

    invalid_payload = dict(payload, lead_id=999)
    invalid = client.post(
        "/api/v2/appointments",
        json=invalid_payload,
        headers={"X-CSRF-Token": csrf_token},
    )

    assert without_csrf.status_code == 403
    assert other_session.status_code == 404
    assert invalid.status_code == 400
    assert _appointment_count() == 0
    assert _appointment_quota_count() == 0


def test_api_rejects_non_allowlisted_or_out_of_domain_json_without_writes(
    client, caplog
):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    base = _valid_api_payload(assessment_id)

    invalid_payloads = []
    for missing in (
        "assessment_id",
        "submission_key",
        "preferred_date",
        "time_slot",
    ):
        payload = dict(base)
        payload.pop(missing)
        invalid_payloads.append(payload)
    invalid_payloads.extend(
        (
            dict(base, contact_name="不应收集"),
            dict(base, lead_id=1),
            dict(base, assessment_id=True),
            dict(base, assessment_id="1"),
            dict(base, assessment_id=0),
            dict(
                base,
                submission_key="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            ),
            dict(base, submission_key="not-a-uuid"),
            dict(base, preferred_date="2026-08-19"),
            dict(base, preferred_date="2026-11-19"),
            dict(base, preferred_date="2026-8-20"),
            dict(base, preferred_date="20260820"),
            dict(base, preferred_date="2026-08-20T00:00:00"),
            dict(base, time_slot="noon"),
            dict(base, time_slot="Morning"),
            dict(base, time_slot=["private-slot-list-marker"]),
            dict(base, time_slot={"private-slot-object-marker": "morning"}),
            dict(base, note=None),
            dict(base, note="字" * 501),
        )
    )

    responses = [
        client.post(
            "/api/v2/appointments",
            json=payload,
            headers={"X-CSRF-Token": csrf_token},
        )
        for payload in invalid_payloads
    ]

    assert {response.status_code for response in responses} == {400}
    assert all(
        response.get_json() == {"error": "invalid appointment payload"}
        for response in responses
    )
    assert _appointment_count() == 0
    assert _appointment_quota_count() == 0
    assert "private-slot-list-marker" not in caplog.text
    assert "private-slot-object-marker" not in caplog.text


def test_shanghai_date_window_accepts_today_and_ninetieth_day_inclusive(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    today = _valid_api_payload(assessment_id)
    today.pop("note")
    today["time_slot"] = "morning"
    ninetieth_day = dict(
        today,
        submission_key=SUBMISSION_KEY_2,
        preferred_date="2026-11-18",
        time_slot="evening",
    )
    afternoon = dict(
        today,
        submission_key=SUBMISSION_KEY_3,
        preferred_date="2026-08-21",
        time_slot="afternoon",
    )

    first = client.post(
        "/api/v2/appointments",
        json=today,
        headers={"X-CSRF-Token": csrf_token},
    )
    last = client.post(
        "/api/v2/appointments",
        json=ninetieth_day,
        headers={"X-CSRF-Token": csrf_token},
    )
    middle = client.post(
        "/api/v2/appointments",
        json=afternoon,
        headers={"X-CSRF-Token": csrf_token},
    )

    assert first.status_code == 200
    assert last.status_code == 200
    assert middle.status_code == 200
    db = models.get_db()
    try:
        rows = db.execute(
            "SELECT preferred_date,time_slot,note FROM appointments ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("2026-08-20", "morning", None),
            ("2026-11-18", "evening", None),
            ("2026-08-21", "afternoon", None),
        ]
    finally:
        db.close()


def test_same_api_request_returns_original_id_and_current_status(client):
    from appointment_repository import transition_appointment

    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    payload = _valid_api_payload(assessment_id)
    headers = {"X-CSRF-Token": csrf_token}
    first = client.post("/api/v2/appointments", json=payload, headers=headers)
    db = models.get_db()
    try:
        transition_appointment(db, first.get_json()["appointment_id"], "confirmed")
    finally:
        db.close()

    replay = client.post("/api/v2/appointments", json=payload, headers=headers)

    assert replay.status_code == 200
    assert replay.get_json() == {
        "success": True,
        "appointment_id": first.get_json()["appointment_id"],
        "status": "confirmed",
    }
    assert _appointment_count() == 1


def test_other_session_cannot_replay_key_or_receive_appointment_identity(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    payload = _valid_api_payload(assessment_id)
    created = client.post(
        "/api/v2/appointments",
        json=payload,
        headers={"X-CSRF-Token": csrf_token},
    )
    assert created.status_code == 200

    other_client = client.application.test_client()
    other_config = other_client.get("/api/v2/assessment/config/manufacturing")
    replay = other_client.post(
        "/api/v2/appointments",
        json=payload,
        headers={"X-CSRF-Token": other_config.get_json()["csrf_token"]},
    )

    assert replay.status_code == 404
    assert b"appointment_id" not in replay.data
    assert payload["submission_key"].encode() not in replay.data
    assert _appointment_count() == 1
    assert _appointment_quota_count() == 1


def test_key_bound_to_another_authorized_assessment_is_generic_conflict(client):
    _use_shanghai_test_clock(client)
    first_assessment, csrf_token = _complete_assessment(client)
    second_assessment, _ = _complete_assessment(
        client, phone="13800138000"
    )
    headers = {"X-CSRF-Token": csrf_token}
    first = client.post(
        "/api/v2/appointments",
        json=_valid_api_payload(first_assessment),
        headers=headers,
    )
    replay = client.post(
        "/api/v2/appointments",
        json=_valid_api_payload(second_assessment),
        headers=headers,
    )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.get_json() == {"error": "appointment conflict"}
    assert "appointment_id" not in replay.get_json()
    assert _appointment_count() == 1


def test_repository_failure_returns_safe_recoverable_response(
    client, monkeypatch
):
    import appointment_repository

    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)

    def fail_submit(*_args, **_kwargs):
        raise RuntimeError("private-appointment-failure-marker")

    monkeypatch.setattr(
        appointment_repository, "submit_appointment_intent", fail_submit
    )
    response = client.post(
        "/api/v2/appointments",
        json=_valid_api_payload(assessment_id),
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "assessment temporarily unavailable",
        "recoverable": True,
    }
    assert b"private-appointment-failure-marker" not in response.data
    assert _appointment_count() == 0
    assert _appointment_quota_count() == 1


def test_appointment_rate_limit_is_five_per_hashed_public_identity(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)
    payload = _valid_api_payload(assessment_id)
    first_identity = {
        "X-CSRF-Token": csrf_token,
        "X-Forwarded-For": "198.51.100.10",
    }
    second_identity = {
        "X-CSRF-Token": csrf_token,
        "X-Forwarded-For": "198.51.100.11",
    }

    accepted = [
        client.post(
            "/api/v2/appointments", json=payload, headers=first_identity
        )
        for _ in range(5)
    ]
    limited = client.post(
        "/api/v2/appointments", json=payload, headers=first_identity
    )
    separate = client.post(
        "/api/v2/appointments", json=payload, headers=second_identity
    )

    assert [response.status_code for response in accepted] == [200] * 5
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "3600"
    assert separate.status_code == 200
    assert _appointment_count() == 1


def test_report_renders_accessible_private_appointment_intent_form(client):
    _use_shanghai_test_clock(client)
    assessment_id, csrf_token = _complete_assessment(client)

    response = client.get(f"/assessment/report/{assessment_id}")

    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one(
        'form#appointment-intent-form[action="/api/v2/appointments"]'
    )
    assert form is not None
    assert form.get("method", "").lower() == "post"
    date_input = form.select_one(
        'input#appointment-date[name="preferred_date"][type="date"]'
    )
    assert date_input["min"] == "2026-08-20"
    assert date_input["max"] == "2026-11-18"
    assert date_input.has_attr("required")
    assert form.select_one('label[for="appointment-date"]')

    slot_group = form.select_one("fieldset#appointment-time-slots")
    assert slot_group.select_one("legend")
    radios = slot_group.select('input[type="radio"][name="time_slot"]')
    assert {radio["value"] for radio in radios} == {
        "morning",
        "afternoon",
        "evening",
    }
    assert all(
        radio.has_attr("required")
        and slot_group.select_one(f'label[for="{radio["id"]}"]')
        for radio in radios
    )

    note = form.select_one('textarea#appointment-note[name="note"]')
    assert note["maxlength"] == "500"
    assert not note.has_attr("required")
    assert form.select_one('label[for="appointment-note"]')
    assessment = form.select_one(
        'input[name="assessment_id"][type="hidden"]'
    )
    submission = form.select_one(
        'input[name="submission_key"][type="hidden"]'
    )
    csrf = form.select_one('input[name="csrf_token"][type="hidden"]')
    assert assessment["value"] == str(assessment_id)
    submission_uuid = uuid.UUID(submission["value"])
    assert submission_uuid.version == 4
    assert str(submission_uuid) == submission["value"]
    assert csrf["value"] == csrf_token

    assert form.select_one('[role="status"][aria-live="polite"]')
    assert form.select_one('[role="alert"]')
    assert form.select_one('button[type="submit"]')
    assert page.select_one('script[src="/static/js/report.js"][defer]')
    assert not form.select(
        'input[name="company_name"],input[name="contact_name"],'
        'input[name="phone"],input[name="email"],input[name="wechat"],'
        'input[name="lead_id"]'
    )
    assert b"sessionStorage" not in response.data
