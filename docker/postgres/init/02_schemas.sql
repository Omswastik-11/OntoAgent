-- 02_schemas.sql
-- Base table definitions for kb and ops schemas

CREATE TABLE IF NOT EXISTS kb.policy_chunks (
  chunk_id     BIGSERIAL PRIMARY KEY,
  doc_id       TEXT NOT NULL,
  doc_title    TEXT NOT NULL,
  section      TEXT NOT NULL,
  content      TEXT NOT NULL,
  embedding    vector(384) NOT NULL,
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  trust_level  TEXT NOT NULL DEFAULT 'internal' CHECK (trust_level IN ('internal','untrusted')),
  quarantined  BOOLEAN NOT NULL DEFAULT false,
  scan_score   REAL NOT NULL DEFAULT 0,
  metadata     JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS policy_chunks_embedding_idx ON kb.policy_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS policy_chunks_tsv_idx ON kb.policy_chunks USING gin (tsv);

GRANT SELECT ON kb.policy_chunks TO ontoagent_kb;
GRANT SELECT, INSERT, UPDATE, DELETE ON kb.policy_chunks TO ontoagent_admin;

CREATE TABLE IF NOT EXISTS ops.refund_tickets (
  ticket_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id         TEXT NOT NULL,
  amount           NUMERIC(12,2) NOT NULL,
  reason_code      TEXT NOT NULL,
  policy_ref       TEXT NOT NULL,
  idempotency_key  TEXT UNIQUE NOT NULL,
  requested_by     TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'created',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.seller_notifications (
  notification_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id        TEXT NOT NULL,
  template_id      TEXT NOT NULL,
  params           JSONB NOT NULL DEFAULT '{}',
  idempotency_key  TEXT UNIQUE NOT NULL,
  requested_by     TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'queued',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.used_tokens (
  jti              TEXT PRIMARY KEY,
  thread_id        TEXT NOT NULL,
  tool             TEXT NOT NULL,
  approver         TEXT NOT NULL,
  used_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.audit_log (
  audit_id         BIGSERIAL PRIMARY KEY,
  event_type       TEXT NOT NULL,
  actor_id         TEXT NOT NULL,
  thread_id        TEXT NOT NULL,
  payload          JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

GRANT SELECT, INSERT ON ops.refund_tickets TO ontoagent_ops;
GRANT SELECT ON ops.refund_tickets TO ontoagent_app;
GRANT SELECT, INSERT ON ops.seller_notifications TO ontoagent_ops;
GRANT SELECT, INSERT ON ops.used_tokens TO ontoagent_ops;
GRANT INSERT, SELECT ON ops.audit_log TO ontoagent_ops, ontoagent_app;
GRANT USAGE, SELECT ON SEQUENCE ops.audit_log_audit_id_seq TO ontoagent_ops, ontoagent_app;
