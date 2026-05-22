-- Day-103d: drop the duplicate tables created by Day-103a/b before ingestion lands.
-- Idempotent. Safe to run even if migrations 051/052 were never applied.
DROP TABLE IF EXISTS concalls;
DROP TABLE IF EXISTS annual_reports;
