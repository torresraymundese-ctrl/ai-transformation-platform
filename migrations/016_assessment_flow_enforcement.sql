DROP TRIGGER IF EXISTS lead_consent_insert_legal_guard;
CREATE TRIGGER lead_consent_insert_legal_guard
BEFORE INSERT ON lead_consents
WHEN NOT EXISTS (
    SELECT 1 FROM legal_documents d
    WHERE d.id=NEW.legal_version_id
      AND d.document_type='privacy'
      AND d.version_code=NEW.policy_version
      AND d.status IN ('published','archived')
      AND d.mode='internal'
      AND d.reviewed_content_sha256=d.content_sha256
      AND d.legal_review_confirmed_at IS NOT NULL
)
BEGIN
    SELECT RAISE(ABORT,'invalid consent legal binding');
END;

DROP TRIGGER IF EXISTS lead_consent_update_legal_guard;
CREATE TRIGGER lead_consent_update_legal_guard
BEFORE UPDATE ON lead_consents
WHEN NOT (
    (
        OLD.legal_version_id IS NOT NULL AND
        NEW.legal_version_id IS OLD.legal_version_id AND
        NEW.policy_version IS OLD.policy_version AND
        EXISTS (
            SELECT 1 FROM legal_documents d
            WHERE d.id=NEW.legal_version_id
              AND d.document_type='privacy'
              AND d.version_code=NEW.policy_version
              AND d.status IN ('published','archived')
              AND d.mode='internal'
              AND d.reviewed_content_sha256=d.content_sha256
              AND d.legal_review_confirmed_at IS NOT NULL
        )
    ) OR (
        OLD.legal_version_id IS NULL AND
        NEW.legal_version_id IS NOT NULL AND
        NEW.id IS OLD.id AND
        NEW.lead_id IS OLD.lead_id AND
        NEW.policy_version IS OLD.policy_version AND
        NEW.consented_at IS OLD.consented_at AND
        NEW.source IS OLD.source AND
        NEW.identity_hash IS OLD.identity_hash AND
        NEW.created_at IS OLD.created_at AND
        EXISTS (
            SELECT 1 FROM legal_documents d
            WHERE d.id=NEW.legal_version_id
              AND d.document_type='privacy'
              AND d.version_code=OLD.policy_version
              AND d.version_code=NEW.policy_version
              AND d.status IN ('published','archived')
              AND d.mode='external_legacy'
              AND d.reviewed_content_sha256 IS NULL
              AND d.legal_review_confirmed_at IS NULL
        )
    )
)
BEGIN
    SELECT RAISE(ABORT,'invalid consent legal update');
END;

DROP TRIGGER IF EXISTS assessment_legal_versions_insert_guard;
CREATE TRIGGER assessment_legal_versions_insert_guard
BEFORE INSERT ON assessment_legal_versions
WHEN NOT EXISTS (
    SELECT 1 FROM legal_documents d
    WHERE d.id=NEW.legal_version_id
      AND d.document_type=NEW.document_type
      AND d.version_code=NEW.version_code
      AND d.content_sha256=NEW.digest
      AND d.mode='internal'
      AND d.reviewed_content_sha256=d.content_sha256
      AND d.legal_review_confirmed_at IS NOT NULL
      AND d.status IN ('published','archived')
)
BEGIN
    SELECT RAISE(ABORT,'invalid assessment legal snapshot');
END;
