ALTER TABLE assessment_versions ADD COLUMN copied_from_id INTEGER REFERENCES assessment_versions(id);
ALTER TABLE assessment_versions ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1 CHECK(lock_version > 0);
ALTER TABLE assessment_versions ADD COLUMN validated_digest TEXT;
ALTER TABLE assessment_versions ADD COLUMN updated_at TEXT;
UPDATE assessment_versions SET updated_at=created_at WHERE updated_at IS NULL;
CREATE INDEX assessment_versions_admin_list ON assessment_versions(status,updated_at DESC,id DESC);

CREATE TABLE assessment_release_industries (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 code TEXT NOT NULL, label TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(assessment_version_id,code), UNIQUE(assessment_version_id,sort_order),
 UNIQUE(id,assessment_version_id), UNIQUE(id,assessment_version_id,code),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE assessment_release_subbranches (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 industry_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(assessment_version_id,code), UNIQUE(industry_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(industry_id) REFERENCES assessment_release_industries(id),
 FOREIGN KEY(industry_id,assessment_version_id) REFERENCES assessment_release_industries(id,assessment_version_id));
CREATE TABLE assessment_release_departments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 industry_id INTEGER NOT NULL, branch_code TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(industry_id,code), UNIQUE(industry_id,sort_order),
 UNIQUE(assessment_version_id,branch_code,code),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(industry_id) REFERENCES assessment_release_industries(id),
 FOREIGN KEY(industry_id,assessment_version_id) REFERENCES assessment_release_industries(id,assessment_version_id),
 FOREIGN KEY(industry_id,assessment_version_id,branch_code) REFERENCES assessment_release_industries(id,assessment_version_id,code),
 FOREIGN KEY(assessment_version_id,branch_code) REFERENCES assessment_release_industries(assessment_version_id,code));
CREATE TABLE assessment_release_pain_points (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 industry_id INTEGER NOT NULL, branch_code TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(industry_id,code), UNIQUE(industry_id,sort_order),
 UNIQUE(assessment_version_id,branch_code,code),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(industry_id) REFERENCES assessment_release_industries(id),
 FOREIGN KEY(industry_id,assessment_version_id) REFERENCES assessment_release_industries(id,assessment_version_id),
 FOREIGN KEY(industry_id,assessment_version_id,branch_code) REFERENCES assessment_release_industries(id,assessment_version_id,code),
 FOREIGN KEY(assessment_version_id,branch_code) REFERENCES assessment_release_industries(assessment_version_id,code));
CREATE TABLE assessment_release_company_sizes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 code TEXT NOT NULL, label TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(assessment_version_id,code), UNIQUE(assessment_version_id,sort_order),
 UNIQUE(id,assessment_version_id),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE assessment_release_public_labels (
 assessment_version_id INTEGER NOT NULL,
 family TEXT NOT NULL CHECK(family IN (
  'risk_labels','risk_explanations','dimensions','maturities',
  'integrations','roi_groups','roi_options')),
 parent_code TEXT NOT NULL DEFAULT '', code TEXT NOT NULL,
 label TEXT NOT NULL, sort_order INTEGER NOT NULL CHECK(sort_order > 0),
 PRIMARY KEY(assessment_version_id,family,parent_code,code),
 UNIQUE(assessment_version_id,family,parent_code,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE assessment_release_roi_ranges (
 assessment_version_id INTEGER NOT NULL,
 option_group TEXT NOT NULL CHECK(option_group IN (
  'headcount','monthly_hours','monthly_cost','loss_factor','budget')),
 code TEXT NOT NULL, low_value TEXT NOT NULL, mid_value TEXT NOT NULL,
 high_value TEXT NOT NULL, sort_order INTEGER NOT NULL CHECK(sort_order > 0),
 PRIMARY KEY(assessment_version_id,option_group,code),
 UNIQUE(assessment_version_id,option_group,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));

CREATE TABLE assessment_release_scenarios (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 code TEXT NOT NULL, category_code TEXT NOT NULL, public_name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', minimum_business_value INTEGER NOT NULL,
 minimum_process INTEGER NOT NULL, minimum_data INTEGER NOT NULL,
 minimum_systems INTEGER NOT NULL, minimum_organization INTEGER NOT NULL,
 minimum_delivery INTEGER NOT NULL, integration_level TEXT NOT NULL CHECK(integration_level IN ('low','medium','high')),
 min_weeks INTEGER NOT NULL, max_weeks INTEGER NOT NULL,
 fallback_only INTEGER NOT NULL CHECK(fallback_only IN (0,1)), sort_order INTEGER NOT NULL,
 UNIQUE(assessment_version_id,code), UNIQUE(assessment_version_id,sort_order),
 UNIQUE(id,assessment_version_id),
 CHECK(min_weeks > 0 AND min_weeks <= max_weeks),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE assessment_release_scenario_branches (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL,
 branch_code TEXT NOT NULL, sort_order INTEGER NOT NULL,
 PRIMARY KEY(scenario_id,branch_code), UNIQUE(scenario_id,sort_order),
 UNIQUE(assessment_version_id,scenario_id,branch_code),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id),
 FOREIGN KEY(assessment_version_id,branch_code)
  REFERENCES assessment_release_industries(assessment_version_id,code));
CREATE TABLE assessment_release_scenario_departments (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL,
 branch_code TEXT NOT NULL, department_code TEXT NOT NULL, sort_order INTEGER NOT NULL,
 PRIMARY KEY(scenario_id,branch_code,department_code), UNIQUE(scenario_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id),
 FOREIGN KEY(assessment_version_id,scenario_id,branch_code)
  REFERENCES assessment_release_scenario_branches(assessment_version_id,scenario_id,branch_code),
 FOREIGN KEY(assessment_version_id,branch_code,department_code)
  REFERENCES assessment_release_departments(assessment_version_id,branch_code,code));
CREATE TABLE assessment_release_scenario_pains (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL,
 branch_code TEXT NOT NULL, pain_code TEXT NOT NULL, sort_order INTEGER NOT NULL,
 PRIMARY KEY(scenario_id,branch_code,pain_code), UNIQUE(scenario_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id),
 FOREIGN KEY(assessment_version_id,scenario_id,branch_code)
  REFERENCES assessment_release_scenario_branches(assessment_version_id,scenario_id,branch_code),
 FOREIGN KEY(assessment_version_id,branch_code,pain_code)
  REFERENCES assessment_release_pain_points(assessment_version_id,branch_code,code));
CREATE TABLE assessment_release_scenario_budgets (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL,
 budget_code TEXT NOT NULL, sort_order INTEGER NOT NULL,
 PRIMARY KEY(scenario_id,budget_code), UNIQUE(scenario_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id));
CREATE TABLE assessment_release_scenario_risks (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL,
 risk_code TEXT NOT NULL, sort_order INTEGER NOT NULL,
 PRIMARY KEY(scenario_id,risk_code), UNIQUE(scenario_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id));
CREATE TABLE assessment_release_scenario_roi (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL UNIQUE,
 efficiency_low TEXT NOT NULL, efficiency_mid TEXT NOT NULL, efficiency_high TEXT NOT NULL,
 loss_improvement_low TEXT NOT NULL, loss_improvement_mid TEXT NOT NULL, loss_improvement_high TEXT NOT NULL,
 annual_support_rate_low TEXT NOT NULL, annual_support_rate_mid TEXT NOT NULL, annual_support_rate_high TEXT NOT NULL,
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id));

CREATE TABLE assessment_release_services (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL,
 code TEXT NOT NULL, category TEXT NOT NULL, public_name TEXT NOT NULL,
 min_budget TEXT NOT NULL, max_budget TEXT NOT NULL, min_weeks INTEGER NOT NULL,
 max_weeks INTEGER NOT NULL, support_days INTEGER NOT NULL,
 support_description TEXT NOT NULL, public_disclaimer TEXT NOT NULL, sort_order INTEGER NOT NULL,
 UNIQUE(assessment_version_id,code), UNIQUE(assessment_version_id,sort_order),
 UNIQUE(id,assessment_version_id),
 CHECK(min_weeks > 0 AND min_weeks <= max_weeks), CHECK(support_days >= 0),
 CHECK(CAST(min_budget AS NUMERIC) > 0 AND CAST(max_budget AS NUMERIC) >= CAST(min_budget AS NUMERIC)),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE assessment_release_scenario_services (
 assessment_version_id INTEGER NOT NULL, scenario_id INTEGER NOT NULL UNIQUE, service_id INTEGER NOT NULL,
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id),
 FOREIGN KEY(scenario_id) REFERENCES assessment_release_scenarios(id),
 FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(scenario_id,assessment_version_id) REFERENCES assessment_release_scenarios(id,assessment_version_id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));
CREATE TABLE assessment_release_service_deliverables (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 value TEXT NOT NULL, sort_order INTEGER NOT NULL, UNIQUE(service_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id), FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));
CREATE TABLE assessment_release_service_steps (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 value TEXT NOT NULL, sort_order INTEGER NOT NULL, UNIQUE(service_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id), FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));
CREATE TABLE assessment_release_service_prerequisites (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 value TEXT NOT NULL, sort_order INTEGER NOT NULL, UNIQUE(service_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id), FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));
CREATE TABLE assessment_release_service_exclusions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 value TEXT NOT NULL, sort_order INTEGER NOT NULL, UNIQUE(service_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id), FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));
CREATE TABLE assessment_release_service_acceptance (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 value TEXT NOT NULL, sort_order INTEGER NOT NULL, UNIQUE(service_id,sort_order),
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id), FOREIGN KEY(service_id) REFERENCES assessment_release_services(id),
 FOREIGN KEY(service_id,assessment_version_id) REFERENCES assessment_release_services(id,assessment_version_id));

CREATE TABLE assessment_version_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_version_id INTEGER NOT NULL UNIQUE,
 schema_version TEXT NOT NULL, canonical_json TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), created_at TEXT NOT NULL,
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));
CREATE TABLE active_assessment_version (
 singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
 assessment_version_id INTEGER NOT NULL UNIQUE, updated_at TEXT NOT NULL,
 FOREIGN KEY(assessment_version_id) REFERENCES assessment_versions(id));

CREATE TRIGGER validate_assessment_snapshot_insert BEFORE INSERT ON assessment_version_snapshots
BEGIN SELECT CASE WHEN NOT EXISTS(
 SELECT 1 FROM assessment_versions v
 WHERE v.id=NEW.assessment_version_id
  AND typeof(NEW.canonical_json)='text'
  AND NEW.schema_version='2.0'
  AND json_valid(NEW.canonical_json)=1
  AND json_extract(NEW.canonical_json,'$.schema_version')=NEW.schema_version
  AND json_extract(NEW.canonical_json,'$.release.code')=v.code
  AND json_extract(NEW.canonical_json,'$.release.name')=v.name
  AND json_extract(NEW.canonical_json,'$.release.pain_selection.minimum')=v.pain_min_selections
  AND json_extract(NEW.canonical_json,'$.release.pain_selection.maximum')=v.pain_max_selections
  AND canonical_release_valid(NEW.canonical_json,v.code,v.name,v.pain_min_selections,v.pain_max_selections)=1
  AND v.validated_digest=NEW.sha256
  AND NEW.sha256=lower(NEW.sha256)
  AND NEW.sha256 NOT GLOB '*[^0-9a-f]*'
  AND sha256_utf8(NEW.canonical_json)=NEW.sha256)
 THEN RAISE(ABORT,'assessment snapshot is invalid') END; END;
CREATE TRIGGER prevent_assessment_snapshot_update BEFORE UPDATE ON assessment_version_snapshots
BEGIN SELECT RAISE(ABORT,'assessment snapshot is immutable'); END;
CREATE TRIGGER prevent_assessment_snapshot_delete BEFORE DELETE ON assessment_version_snapshots
BEGIN SELECT RAISE(ABORT,'assessment snapshot is immutable'); END;

CREATE TRIGGER validate_assessment_version_publish BEFORE UPDATE OF status ON assessment_versions
WHEN OLD.status='draft' AND NEW.status<>'draft'
BEGIN SELECT CASE WHEN NOT EXISTS(
 SELECT 1 FROM assessment_version_snapshots s
 WHERE NEW.status='published' AND s.assessment_version_id=NEW.id
  AND s.schema_version='2.0'
  AND json_valid(s.canonical_json)=1
  AND json_extract(s.canonical_json,'$.schema_version')=s.schema_version
  AND json_extract(s.canonical_json,'$.release.code')=NEW.code
  AND json_extract(s.canonical_json,'$.release.name')=NEW.name
  AND json_extract(s.canonical_json,'$.release.pain_selection.minimum')=NEW.pain_min_selections
  AND json_extract(s.canonical_json,'$.release.pain_selection.maximum')=NEW.pain_max_selections
  AND canonical_release_valid(s.canonical_json,NEW.code,NEW.name,NEW.pain_min_selections,NEW.pain_max_selections)=1
  AND NEW.validated_digest=s.sha256
  AND s.sha256=lower(s.sha256)
  AND s.sha256 NOT GLOB '*[^0-9a-f]*'
  AND sha256_utf8(s.canonical_json)=s.sha256)
 THEN RAISE(ABORT,'assessment publish snapshot is invalid') END; END;

CREATE TRIGGER protect_snapshotted_assessment_version_update BEFORE UPDATE ON assessment_versions
WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots s WHERE s.assessment_version_id=OLD.id)
 AND NOT (OLD.status='draft' AND NEW.status='published' AND NEW.code=OLD.code AND NEW.name=OLD.name
  AND NEW.pain_min_selections=OLD.pain_min_selections AND NEW.pain_max_selections=OLD.pain_max_selections
  AND NEW.copied_from_id IS OLD.copied_from_id AND NEW.validated_digest=OLD.validated_digest
  AND NEW.created_at=OLD.created_at AND OLD.published_at IS NULL AND NEW.published_at IS NOT NULL
  AND NEW.lock_version=OLD.lock_version+1 AND NEW.updated_at IS NOT OLD.updated_at)
 AND NOT (OLD.status='published' AND NEW.status='archived' AND NEW.code=OLD.code AND NEW.name=OLD.name
  AND NEW.pain_min_selections=OLD.pain_min_selections AND NEW.pain_max_selections=OLD.pain_max_selections
  AND NEW.copied_from_id IS OLD.copied_from_id AND NEW.validated_digest=OLD.validated_digest
  AND NEW.created_at=OLD.created_at AND NEW.published_at IS OLD.published_at
  AND NEW.lock_version=OLD.lock_version+1 AND NEW.updated_at IS NOT OLD.updated_at
  AND NOT EXISTS(SELECT 1 FROM active_assessment_version a WHERE a.assessment_version_id=OLD.id))
BEGIN SELECT RAISE(ABORT,'snapshotted assessment version is immutable'); END;
CREATE TRIGGER protect_unsnapshotted_published_assessment_version_update BEFORE UPDATE ON assessment_versions
WHEN OLD.status='published' AND NOT EXISTS(SELECT 1 FROM assessment_version_snapshots s WHERE s.assessment_version_id=OLD.id)
 AND NOT (OLD.code='v2.0-2026-08-19' AND OLD.copied_from_id IS NULL
  AND NEW.status=OLD.status AND NEW.code=OLD.code AND NEW.name=OLD.name
  AND NEW.pain_min_selections=OLD.pain_min_selections AND NEW.pain_max_selections=OLD.pain_max_selections
  AND NEW.copied_from_id IS OLD.copied_from_id AND OLD.validated_digest IS NULL AND length(NEW.validated_digest)=64
  AND NEW.created_at=OLD.created_at AND NEW.published_at IS OLD.published_at
  AND NEW.lock_version=OLD.lock_version AND NEW.updated_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'published assessment version is immutable'); END;
CREATE TRIGGER protect_snapshotted_assessment_version_delete BEFORE DELETE ON assessment_versions
WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots s WHERE s.assessment_version_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'snapshotted assessment version is immutable'); END;
CREATE TRIGGER protect_published_assessment_version_delete BEFORE DELETE ON assessment_versions
WHEN OLD.status IN ('published','archived')
BEGIN SELECT RAISE(ABORT,'published assessment version is immutable'); END;
CREATE TRIGGER validate_active_assessment_version_insert BEFORE INSERT ON active_assessment_version
BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM assessment_versions v JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id
 WHERE v.id=NEW.assessment_version_id AND v.status='published' AND v.validated_digest=s.sha256
  AND s.schema_version='2.0' AND json_valid(s.canonical_json)=1
  AND json_extract(s.canonical_json,'$.schema_version')=s.schema_version
  AND json_extract(s.canonical_json,'$.release.code')=v.code
  AND json_extract(s.canonical_json,'$.release.name')=v.name
  AND json_extract(s.canonical_json,'$.release.pain_selection.minimum')=v.pain_min_selections
  AND json_extract(s.canonical_json,'$.release.pain_selection.maximum')=v.pain_max_selections
  AND canonical_release_valid(s.canonical_json,v.code,v.name,v.pain_min_selections,v.pain_max_selections)=1
  AND s.sha256=lower(s.sha256) AND s.sha256 NOT GLOB '*[^0-9a-f]*'
  AND sha256_utf8(s.canonical_json)=s.sha256)
 THEN RAISE(ABORT,'active assessment release is invalid') END; END;
CREATE TRIGGER validate_active_assessment_version_update BEFORE UPDATE ON active_assessment_version
BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM assessment_versions v JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id
 WHERE v.id=NEW.assessment_version_id AND v.status='published' AND v.validated_digest=s.sha256
  AND s.schema_version='2.0' AND json_valid(s.canonical_json)=1
  AND json_extract(s.canonical_json,'$.schema_version')=s.schema_version
  AND json_extract(s.canonical_json,'$.release.code')=v.code
  AND json_extract(s.canonical_json,'$.release.name')=v.name
  AND json_extract(s.canonical_json,'$.release.pain_selection.minimum')=v.pain_min_selections
  AND json_extract(s.canonical_json,'$.release.pain_selection.maximum')=v.pain_max_selections
  AND canonical_release_valid(s.canonical_json,v.code,v.name,v.pain_min_selections,v.pain_max_selections)=1
  AND s.sha256=lower(s.sha256) AND s.sha256 NOT GLOB '*[^0-9a-f]*'
  AND sha256_utf8(s.canonical_json)=s.sha256)
 THEN RAISE(ABORT,'active assessment release is invalid') END; END;
CREATE TRIGGER prevent_active_assessment_version_delete BEFORE DELETE ON active_assessment_version
BEGIN SELECT RAISE(ABORT,'active assessment release cannot be deleted'); END;

-- Existing version children, including assessment_options through their question owner.
CREATE TRIGGER protect_snapshot_questions_insert BEFORE INSERT ON assessment_questions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_questions_update BEFORE UPDATE ON assessment_questions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_questions_delete BEFORE DELETE ON assessment_questions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_options_insert BEFORE INSERT ON assessment_options WHEN EXISTS(SELECT 1 FROM assessment_questions q JOIN assessment_version_snapshots s ON s.assessment_version_id=q.assessment_version_id WHERE q.id=NEW.question_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_options_update BEFORE UPDATE ON assessment_options WHEN EXISTS(SELECT 1 FROM assessment_questions q JOIN assessment_version_snapshots s ON s.assessment_version_id=q.assessment_version_id WHERE q.id=OLD.question_id) OR EXISTS(SELECT 1 FROM assessment_questions q JOIN assessment_version_snapshots s ON s.assessment_version_id=q.assessment_version_id WHERE q.id=NEW.question_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_options_delete BEFORE DELETE ON assessment_options WHEN EXISTS(SELECT 1 FROM assessment_questions q JOIN assessment_version_snapshots s ON s.assessment_version_id=q.assessment_version_id WHERE q.id=OLD.question_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;

CREATE TRIGGER protect_snapshot_weights_insert BEFORE INSERT ON assessment_branch_weights WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_weights_update BEFORE UPDATE ON assessment_branch_weights WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_weights_delete BEFORE DELETE ON assessment_branch_weights WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_benchmarks_insert BEFORE INSERT ON industry_benchmarks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_benchmarks_update BEFORE UPDATE ON industry_benchmarks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_benchmarks_delete BEFORE DELETE ON industry_benchmarks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_ranges_insert BEFORE INSERT ON roi_option_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_ranges_update BEFORE UPDATE ON roi_option_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_ranges_delete BEFORE DELETE ON roi_option_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_legacy_roi_insert BEFORE INSERT ON scenario_roi_profiles WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_legacy_roi_update BEFORE UPDATE ON scenario_roi_profiles WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_legacy_roi_delete BEFORE DELETE ON scenario_roi_profiles WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_industries_insert BEFORE INSERT ON assessment_release_industries WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_industries_update BEFORE UPDATE ON assessment_release_industries WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_industries_delete BEFORE DELETE ON assessment_release_industries WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_subbranches_insert BEFORE INSERT ON assessment_release_subbranches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_subbranches_update BEFORE UPDATE ON assessment_release_subbranches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_subbranches_delete BEFORE DELETE ON assessment_release_subbranches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_departments_insert BEFORE INSERT ON assessment_release_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_departments_update BEFORE UPDATE ON assessment_release_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_departments_delete BEFORE DELETE ON assessment_release_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_pains_insert BEFORE INSERT ON assessment_release_pain_points WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_pains_update BEFORE UPDATE ON assessment_release_pain_points WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_pains_delete BEFORE DELETE ON assessment_release_pain_points WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_sizes_insert BEFORE INSERT ON assessment_release_company_sizes WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_sizes_update BEFORE UPDATE ON assessment_release_company_sizes WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_sizes_delete BEFORE DELETE ON assessment_release_company_sizes WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_labels_insert BEFORE INSERT ON assessment_release_public_labels WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_labels_update BEFORE UPDATE ON assessment_release_public_labels WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_labels_delete BEFORE DELETE ON assessment_release_public_labels WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER validate_release_roi_range_insert BEFORE INSERT ON assessment_release_roi_ranges
WHEN NOT EXISTS(SELECT 1 FROM assessment_release_public_labels l
 WHERE l.assessment_version_id=NEW.assessment_version_id AND l.family='roi_options'
 AND l.parent_code=NEW.option_group AND l.code=NEW.code)
BEGIN SELECT RAISE(ABORT,'assessment release ROI range domain is invalid'); END;
CREATE TRIGGER protect_snapshot_release_roi_ranges_insert BEFORE INSERT ON assessment_release_roi_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_roi_ranges_update BEFORE UPDATE ON assessment_release_roi_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_roi_ranges_delete BEFORE DELETE ON assessment_release_roi_ranges WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenarios_insert BEFORE INSERT ON assessment_release_scenarios WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenarios_update BEFORE UPDATE ON assessment_release_scenarios WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenarios_delete BEFORE DELETE ON assessment_release_scenarios WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_branches_insert BEFORE INSERT ON assessment_release_scenario_branches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_branches_update BEFORE UPDATE ON assessment_release_scenario_branches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_branches_delete BEFORE DELETE ON assessment_release_scenario_branches WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_departments_insert BEFORE INSERT ON assessment_release_scenario_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_departments_update BEFORE UPDATE ON assessment_release_scenario_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_departments_delete BEFORE DELETE ON assessment_release_scenario_departments WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_pains_insert BEFORE INSERT ON assessment_release_scenario_pains WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_pains_update BEFORE UPDATE ON assessment_release_scenario_pains WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_pains_delete BEFORE DELETE ON assessment_release_scenario_pains WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_budgets_insert BEFORE INSERT ON assessment_release_scenario_budgets WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_budgets_update BEFORE UPDATE ON assessment_release_scenario_budgets WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_budgets_delete BEFORE DELETE ON assessment_release_scenario_budgets WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER validate_release_scenario_budget_insert BEFORE INSERT ON assessment_release_scenario_budgets
WHEN NOT EXISTS(SELECT 1 FROM assessment_release_public_labels l
 WHERE l.assessment_version_id=NEW.assessment_version_id AND l.family='roi_options'
 AND l.parent_code='budget' AND l.code=NEW.budget_code)
BEGIN SELECT RAISE(ABORT,'assessment release budget domain is invalid'); END;
CREATE TRIGGER validate_release_scenario_budget_update BEFORE UPDATE ON assessment_release_scenario_budgets
WHEN NOT EXISTS(SELECT 1 FROM assessment_release_public_labels l
 WHERE l.assessment_version_id=NEW.assessment_version_id AND l.family='roi_options'
 AND l.parent_code='budget' AND l.code=NEW.budget_code)
BEGIN SELECT RAISE(ABORT,'assessment release budget domain is invalid'); END;
CREATE TRIGGER protect_snapshot_release_scenario_risks_insert BEFORE INSERT ON assessment_release_scenario_risks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_risks_update BEFORE UPDATE ON assessment_release_scenario_risks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_risks_delete BEFORE DELETE ON assessment_release_scenario_risks WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER validate_release_scenario_risk_insert BEFORE INSERT ON assessment_release_scenario_risks
WHEN NOT EXISTS(SELECT 1 FROM assessment_release_public_labels l
 WHERE l.assessment_version_id=NEW.assessment_version_id AND l.family='risk_labels'
 AND l.parent_code='' AND l.code=NEW.risk_code)
BEGIN SELECT RAISE(ABORT,'assessment release risk domain is invalid'); END;
CREATE TRIGGER validate_release_scenario_risk_update BEFORE UPDATE ON assessment_release_scenario_risks
WHEN NOT EXISTS(SELECT 1 FROM assessment_release_public_labels l
 WHERE l.assessment_version_id=NEW.assessment_version_id AND l.family='risk_labels'
 AND l.parent_code='' AND l.code=NEW.risk_code)
BEGIN SELECT RAISE(ABORT,'assessment release risk domain is invalid'); END;
CREATE TRIGGER protect_snapshot_release_scenario_roi_insert BEFORE INSERT ON assessment_release_scenario_roi WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_roi_update BEFORE UPDATE ON assessment_release_scenario_roi WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_roi_delete BEFORE DELETE ON assessment_release_scenario_roi WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_services_insert BEFORE INSERT ON assessment_release_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_services_update BEFORE UPDATE ON assessment_release_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_services_delete BEFORE DELETE ON assessment_release_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_services_insert BEFORE INSERT ON assessment_release_scenario_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_services_update BEFORE UPDATE ON assessment_release_scenario_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_scenario_services_delete BEFORE DELETE ON assessment_release_scenario_services WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_deliverables_insert BEFORE INSERT ON assessment_release_service_deliverables WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_deliverables_update BEFORE UPDATE ON assessment_release_service_deliverables WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_deliverables_delete BEFORE DELETE ON assessment_release_service_deliverables WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_steps_insert BEFORE INSERT ON assessment_release_service_steps WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_steps_update BEFORE UPDATE ON assessment_release_service_steps WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_steps_delete BEFORE DELETE ON assessment_release_service_steps WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_prerequisites_insert BEFORE INSERT ON assessment_release_service_prerequisites WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_prerequisites_update BEFORE UPDATE ON assessment_release_service_prerequisites WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_prerequisites_delete BEFORE DELETE ON assessment_release_service_prerequisites WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_exclusions_insert BEFORE INSERT ON assessment_release_service_exclusions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_exclusions_update BEFORE UPDATE ON assessment_release_service_exclusions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_exclusions_delete BEFORE DELETE ON assessment_release_service_exclusions WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_acceptance_insert BEFORE INSERT ON assessment_release_service_acceptance WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_acceptance_update BEFORE UPDATE ON assessment_release_service_acceptance WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) OR EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=NEW.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
CREATE TRIGGER protect_snapshot_release_acceptance_delete BEFORE DELETE ON assessment_release_service_acceptance WHEN EXISTS(SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=OLD.assessment_version_id) BEGIN SELECT RAISE(ABORT,'assessment release child is immutable'); END;
