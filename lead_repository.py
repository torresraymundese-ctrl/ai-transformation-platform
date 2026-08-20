"""Lead and consent writes used by the atomic assessment completion flow."""

from datetime import datetime, timedelta

from validation import (
    ValidationError,
    normalized_mobile,
    validated_email,
    validated_wechat,
)


ORDINARY_QUEUE_STATUSES = ("new", "pending_contact")


def validate_contact(contact):
    return (
        _required_text(contact.company_name, "company_name", 200),
        _required_text(contact.contact_name, "contact_name", 100),
        normalized_mobile(contact.phone),
        validated_email(contact.email),
        validated_wechat(contact.wechat),
    )


def validate_consent(consent, identity_hash):
    if consent.accepted is not True:
        raise ValidationError("consent must be accepted")
    policy_version = _required_text(consent.policy_version, "policy_version", 50)
    source = _required_text(consent.source, "consent_source", 100)
    if (
        not isinstance(identity_hash, str)
        or not identity_hash
        or len(identity_hash) > 256
    ):
        raise ValidationError("identity_hash has an invalid value")
    return policy_version, source


def find_or_create(
    db, contact, source="website_assessment", submitted_at=None
):
    submitted_at = submitted_at or datetime.now().replace(microsecond=0)
    timestamp = submitted_at.isoformat(sep=" ")
    retention = (submitted_at + timedelta(days=365)).isoformat(sep=" ")
    company_name, contact_name, phone, email, wechat = validate_contact(contact)

    existing = db.execute(
        "SELECT id,status FROM leads WHERE phone_normalized=?",
        (phone,),
    ).fetchone()
    if existing is None:
        return db.execute(
            "INSERT INTO leads "
            "(company_name,contact_name,phone_normalized,email,wechat,source,"
            "retention_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                company_name,
                contact_name,
                phone,
                email or None,
                wechat or None,
                source,
                retention,
                timestamp,
                timestamp,
            ),
        ).lastrowid

    lead_id = existing["id"]
    status = existing["status"]
    new_status = "pending_contact" if status == "not_progressing" else status
    new_retention = None if status == "won" else retention
    db.execute(
        "UPDATE leads SET company_name=?,contact_name=?,email=?,wechat=?,status=?,"
        "retention_expires_at=?,updated_at=? WHERE id=?",
        (
            company_name,
            contact_name,
            email or None,
            wechat or None,
            new_status,
            new_retention,
            timestamp,
            lead_id,
        ),
    )
    if new_status != status:
        db.execute(
            "INSERT INTO lead_status_history "
            "(lead_id,previous_status,new_status,actor_text,created_at) "
            "VALUES (?,?,?,?,?)",
            (lead_id, status, new_status, "assessment_submission", timestamp),
        )
    return lead_id


def record_consent(db, lead_id, consent, identity_hash, consented_at=None):
    policy_version, source = validate_consent(consent, identity_hash)
    timestamp = (consented_at or datetime.now().replace(microsecond=0)).isoformat(
        sep=" "
    )
    return db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (lead_id, policy_version, timestamp, source, identity_hash),
    ).lastrowid


def list_ordinary_queue(db):
    placeholders = ",".join("?" for _ in ORDINARY_QUEUE_STATUSES)
    return db.execute(
        f"SELECT * FROM leads WHERE status IN ({placeholders}) "
        "AND anonymized_at IS NULL ORDER BY created_at,id",
        ORDINARY_QUEUE_STATUSES,
    ).fetchall()


def _required_text(value, field_name, maximum):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if not value:
        raise ValidationError(f"{field_name} is required")
    if len(value) > maximum:
        raise ValidationError(f"{field_name} is too long")
    return value
