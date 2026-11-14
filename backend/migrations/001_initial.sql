-- First schema bootstraps via metadata. Optional upgrade indexes:
CREATE INDEX sample_study_group_idx ON composition_samples (study_id,`group`);
CREATE INDEX note_run_status_idx ON resample_notes (run_id,status);
-- Upgrade path for databases created before recovery support. The application
-- also applies these idempotently via recovery_service.ensure_schema().
ALTER TABLE composition_runs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE composition_runs ADD COLUMN lease_token VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN lease_owner VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN lease_expires_at DOUBLE NOT NULL DEFAULT 0;
ALTER TABLE composition_runs ADD COLUMN claimed_at VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN artifact_written_at VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN artifact_key VARCHAR(200) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN result_hash VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN finished_at VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE composition_runs ADD COLUMN recovery_reason VARCHAR(500) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN approved_result_hash VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE composition_runs ADD COLUMN approved_at VARCHAR(64) NOT NULL DEFAULT '';
