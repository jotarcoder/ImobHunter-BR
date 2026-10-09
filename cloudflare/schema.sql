CREATE TABLE IF NOT EXISTS licenses (
 user_id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 email TEXT,
 plan TEXT NOT NULL CHECK(plan IN ('monthly','annual')),
 status TEXT NOT NULL CHECK(status IN ('pending','active','suspended','revoked')),
 key_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 last_seen_at TEXT,
 deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);
CREATE INDEX IF NOT EXISTS idx_licenses_expiry ON licenses(expires_at);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 actor TEXT NOT NULL,
 action TEXT NOT NULL,
 user_id TEXT,
 detail TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);