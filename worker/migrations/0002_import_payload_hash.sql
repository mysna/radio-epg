ALTER TABLE scrape_runs ADD COLUMN payload_hash TEXT;

CREATE INDEX idx_scrape_runs_idempotency_payload
ON scrape_runs(idempotency_key, payload_hash);
