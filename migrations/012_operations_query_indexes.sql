CREATE INDEX operations_leads_ordinary
ON leads(anonymized_at, status, created_at DESC, id DESC);

CREATE INDEX operations_leads_followup
ON leads(anonymized_at, next_followup_at, id);

CREATE INDEX operations_assessments_branch
ON assessments(lead_id, branch_code, completed_at DESC, id DESC);

CREATE INDEX operations_assessments_latest
ON assessments(lead_id, completed_at DESC, id DESC);

CREATE INDEX operations_appointments_queue
ON appointments(status, preferred_date, time_slot, id);

CREATE INDEX operations_appointments_latest
ON appointments(lead_id, created_at DESC, id DESC);

CREATE INDEX operations_data_requests_queue
ON data_subject_requests(status, requested_at DESC, id DESC);

CREATE INDEX operations_content_ordinary
ON content_items(status, updated_at DESC, id DESC);

CREATE INDEX operations_content_scheduled
ON content_items(status, publish_at, id);

CREATE INDEX operations_media_queue
ON media_assets(status, updated_at DESC, id DESC);

CREATE INDEX operations_ingestion_queue
ON ingestion_candidates(state, updated_at DESC, id DESC);
