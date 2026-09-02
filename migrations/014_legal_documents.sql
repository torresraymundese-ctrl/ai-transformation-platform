CREATE TABLE legal_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL
        CHECK(document_type IN ('privacy','terms','roi_disclaimer','ai_content_notice')),
    version_code TEXT NOT NULL
        CHECK(
            length(version_code) BETWEEN 1 AND 64 AND
            substr(version_code,1,1) GLOB '[A-Za-z0-9]' AND
            version_code NOT GLOB '*[^A-Za-z0-9._-]*'
        ),
    mode TEXT NOT NULL CHECK(mode IN ('internal','external_legacy')),
    title TEXT,
    body_summary TEXT,
    body_html TEXT,
    external_url TEXT,
    content_sha256 TEXT NOT NULL
        CHECK(length(content_sha256)=64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    reviewed_content_sha256 TEXT
        CHECK(
            reviewed_content_sha256 IS NULL OR
            (length(reviewed_content_sha256)=64 AND reviewed_content_sha256 NOT GLOB '*[^0-9a-f]*')
        ),
    status TEXT NOT NULL CHECK(status IN ('draft','published','archived')),
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK(lock_version > 0),
    legal_review_confirmed_at TEXT,
    effective_at TEXT NOT NULL,
    published_at TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_type,version_code),
    CHECK(
        (reviewed_content_sha256 IS NULL AND legal_review_confirmed_at IS NULL) OR
        (reviewed_content_sha256 IS NOT NULL AND legal_review_confirmed_at IS NOT NULL)
    ),
    CHECK(
        (mode='internal' AND
         title IS NOT NULL AND length(trim(title)) > 0 AND
         body_summary IS NOT NULL AND length(trim(body_summary)) > 0 AND
         body_html IS NOT NULL AND length(trim(body_html)) > 0 AND
         external_url IS NULL) OR
        (mode='external_legacy' AND document_type='privacy' AND
         title IS NULL AND body_summary IS NULL AND body_html IS NULL AND
         external_url IS NOT NULL AND length(trim(external_url)) > 0 AND
         reviewed_content_sha256 IS NULL AND legal_review_confirmed_at IS NULL)
    ),
    CHECK(
        (status='draft' AND published_at IS NULL AND archived_at IS NULL) OR
        (status='published' AND published_at IS NOT NULL AND archived_at IS NULL) OR
        (status='archived' AND published_at IS NOT NULL AND archived_at IS NOT NULL)
    )
);

CREATE INDEX idx_legal_documents_admin_list
ON legal_documents(document_type,status,updated_at DESC,id DESC);

CREATE TRIGGER legal_document_insert_lifecycle_guard
BEFORE INSERT ON legal_documents
WHEN NOT (
    (NEW.mode='internal' AND NEW.status='draft' AND NEW.lock_version=1 AND
     NEW.reviewed_content_sha256 IS NULL AND NEW.legal_review_confirmed_at IS NULL AND
     NEW.published_at IS NULL AND NEW.archived_at IS NULL) OR
    (NEW.mode='external_legacy' AND NEW.document_type='privacy' AND
     NEW.status='published' AND NEW.lock_version=1 AND
     NEW.reviewed_content_sha256 IS NULL AND NEW.legal_review_confirmed_at IS NULL AND
     NEW.published_at IS NOT NULL AND NEW.archived_at IS NULL)
)
BEGIN
    SELECT RAISE(ABORT,'invalid legal lifecycle insert');
END;

CREATE TABLE active_legal_documents (
    document_type TEXT PRIMARY KEY
        CHECK(document_type IN ('privacy','terms','roi_disclaimer','ai_content_notice')),
    legal_document_id INTEGER NOT NULL UNIQUE REFERENCES legal_documents(id)
);

CREATE TRIGGER legal_active_pointer_insert_guard
BEFORE INSERT ON active_legal_documents
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM legal_documents d
        WHERE d.id=NEW.legal_document_id
          AND d.document_type=NEW.document_type
          AND d.status='published'
          AND d.published_at IS NOT NULL
          AND d.effective_at IS NOT NULL
          AND d.effective_at <= d.published_at
          AND length(d.content_sha256)=64
          AND d.content_sha256 NOT GLOB '*[^0-9a-f]*'
          AND (
              (d.mode='internal' AND
               length(trim(d.title)) > 0 AND
               length(trim(d.body_summary)) > 0 AND
               length(trim(d.body_html)) > 0 AND
               d.external_url IS NULL AND
               d.reviewed_content_sha256=d.content_sha256 AND
               d.legal_review_confirmed_at IS NOT NULL) OR
              (d.mode='external_legacy' AND d.document_type='privacy' AND
               d.title IS NULL AND d.body_summary IS NULL AND d.body_html IS NULL AND
               length(trim(d.external_url)) > 0 AND
               d.reviewed_content_sha256 IS NULL AND
               d.legal_review_confirmed_at IS NULL)
          )
    ) THEN RAISE(ABORT,'invalid active legal document') END;
END;

CREATE TRIGGER legal_active_pointer_update_guard
BEFORE UPDATE ON active_legal_documents
BEGIN
    SELECT CASE WHEN OLD.document_type<>NEW.document_type OR NOT EXISTS (
        SELECT 1 FROM legal_documents d
        WHERE d.id=NEW.legal_document_id
          AND d.document_type=NEW.document_type
          AND d.status='published'
          AND d.published_at IS NOT NULL
          AND d.effective_at IS NOT NULL
          AND d.effective_at <= d.published_at
          AND length(d.content_sha256)=64
          AND d.content_sha256 NOT GLOB '*[^0-9a-f]*'
          AND (
              (d.mode='internal' AND
               length(trim(d.title)) > 0 AND
               length(trim(d.body_summary)) > 0 AND
               length(trim(d.body_html)) > 0 AND
               d.external_url IS NULL AND
               d.reviewed_content_sha256=d.content_sha256 AND
               d.legal_review_confirmed_at IS NOT NULL) OR
              (d.mode='external_legacy' AND d.document_type='privacy' AND
               d.title IS NULL AND d.body_summary IS NULL AND d.body_html IS NULL AND
               length(trim(d.external_url)) > 0 AND
               d.reviewed_content_sha256 IS NULL AND
               d.legal_review_confirmed_at IS NULL)
          )
    ) THEN RAISE(ABORT,'invalid active legal document') END;
END;

CREATE TRIGGER legal_active_pointer_delete_guard
BEFORE DELETE ON active_legal_documents
BEGIN
    SELECT RAISE(ABORT,'active legal pointer is immutable');
END;

CREATE TRIGGER legal_review_cannot_survive_digest_change
BEFORE UPDATE ON legal_documents
WHEN (
    NEW.document_type IS NOT OLD.document_type OR
    NEW.version_code IS NOT OLD.version_code OR
    NEW.mode IS NOT OLD.mode OR
    NEW.title IS NOT OLD.title OR
    NEW.body_summary IS NOT OLD.body_summary OR
    NEW.body_html IS NOT OLD.body_html OR
    NEW.external_url IS NOT OLD.external_url OR
    NEW.content_sha256 IS NOT OLD.content_sha256
) AND (
    NEW.reviewed_content_sha256 IS NOT NULL OR
    NEW.legal_review_confirmed_at IS NOT NULL
)
BEGIN
    SELECT RAISE(ABORT,'stale legal review');
END;

CREATE TRIGGER legal_document_update_lifecycle_guard
BEFORE UPDATE ON legal_documents
WHEN NOT (
    (
        OLD.status='draft' AND NEW.status='draft' AND
        NEW.document_type=OLD.document_type AND
        NEW.version_code=OLD.version_code AND
        NEW.mode=OLD.mode AND
        NEW.created_at=OLD.created_at AND
        NEW.published_at IS NULL AND
        NEW.archived_at IS NULL AND
        NEW.lock_version=OLD.lock_version+1
    ) OR
    (
        OLD.status='draft' AND NEW.status='published' AND
        NEW.document_type=OLD.document_type AND
        NEW.version_code=OLD.version_code AND
        NEW.mode=OLD.mode AND
        NEW.title IS OLD.title AND
        NEW.body_summary IS OLD.body_summary AND
        NEW.body_html IS OLD.body_html AND
        NEW.external_url IS OLD.external_url AND
        NEW.content_sha256=OLD.content_sha256 AND
        NEW.reviewed_content_sha256 IS OLD.reviewed_content_sha256 AND
        NEW.legal_review_confirmed_at IS OLD.legal_review_confirmed_at AND
        NEW.effective_at=OLD.effective_at AND
        NEW.created_at=OLD.created_at AND
        NEW.published_at IS NOT NULL AND
        NEW.archived_at IS NULL AND
        NEW.lock_version=OLD.lock_version+1 AND
        NEW.mode='internal' AND
        NEW.reviewed_content_sha256=NEW.content_sha256 AND
        NEW.legal_review_confirmed_at IS NOT NULL
    ) OR
    (
        OLD.status='published' AND NEW.status='archived' AND
        NEW.document_type=OLD.document_type AND
        NEW.version_code=OLD.version_code AND
        NEW.mode=OLD.mode AND
        NEW.title IS OLD.title AND
        NEW.body_summary IS OLD.body_summary AND
        NEW.body_html IS OLD.body_html AND
        NEW.external_url IS OLD.external_url AND
        NEW.content_sha256=OLD.content_sha256 AND
        NEW.reviewed_content_sha256 IS OLD.reviewed_content_sha256 AND
        NEW.legal_review_confirmed_at IS OLD.legal_review_confirmed_at AND
        NEW.effective_at=OLD.effective_at AND
        NEW.published_at=OLD.published_at AND
        NEW.created_at=OLD.created_at AND
        NEW.archived_at IS NOT NULL AND
        NEW.lock_version=OLD.lock_version+1 AND
        NOT EXISTS(
            SELECT 1 FROM active_legal_documents a
            WHERE a.legal_document_id=OLD.id
        )
    )
)
BEGIN
    SELECT RAISE(ABORT,'invalid legal lifecycle update');
END;

CREATE TRIGGER legal_document_delete_guard
BEFORE DELETE ON legal_documents
WHEN OLD.status IN ('published','archived')
BEGIN
    SELECT RAISE(ABORT,'published legal document is immutable');
END;

ALTER TABLE lead_consents
ADD COLUMN legal_version_id INTEGER REFERENCES legal_documents(id);

CREATE TABLE assessment_legal_versions (
    assessment_id INTEGER NOT NULL REFERENCES assessments(id),
    document_type TEXT NOT NULL
        CHECK(document_type IN ('privacy','terms','roi_disclaimer','ai_content_notice')),
    legal_version_id INTEGER NOT NULL REFERENCES legal_documents(id),
    version_code TEXT NOT NULL
        CHECK(
            length(version_code) BETWEEN 1 AND 64 AND
            substr(version_code,1,1) GLOB '[A-Za-z0-9]' AND
            version_code NOT GLOB '*[^A-Za-z0-9._-]*'
        ),
    digest TEXT NOT NULL
        CHECK(length(digest)=64 AND digest NOT GLOB '*[^0-9a-f]*'),
    UNIQUE(assessment_id,document_type)
);

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

CREATE TRIGGER assessment_legal_versions_update_guard
BEFORE UPDATE ON assessment_legal_versions
BEGIN
    SELECT RAISE(ABORT,'assessment legal snapshot is immutable');
END;

CREATE TRIGGER assessment_legal_versions_delete_guard
BEFORE DELETE ON assessment_legal_versions
BEGIN
    SELECT RAISE(ABORT,'assessment legal snapshot is immutable');
END;
