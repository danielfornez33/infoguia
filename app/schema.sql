CREATE TABLE IF NOT EXISTS company (
  clte BIGINT PRIMARY KEY,
  name TEXT NOT NULL,
  name_norm TEXT,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  description TEXT,
  rating_pct NUMERIC(5,2),
  store_url TEXT,
  source_url TEXT,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  content_sha TEXT
);

CREATE INDEX IF NOT EXISTS idx_company_name_norm ON company (name_norm);
CREATE INDEX IF NOT EXISTS idx_company_last_seen ON company (last_seen);

CREATE TABLE IF NOT EXISTS branch (
  id BIGSERIAL PRIMARY KEY,
  clte BIGINT NOT NULL REFERENCES company(clte) ON DELETE CASCADE,
  branch_key TEXT NOT NULL,
  urbanization TEXT,
  address TEXT,
  city TEXT,
  phones TEXT,
  whatsapp TEXT,
  email TEXT,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clte, branch_key)
);

CREATE INDEX IF NOT EXISTS idx_branch_city ON branch (city);

CREATE TABLE IF NOT EXISTS contact (
  id BIGSERIAL PRIMARY KEY,
  clte BIGINT NOT NULL REFERENCES company(clte) ON DELETE CASCADE,
  branch_key TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL,
  value TEXT NOT NULL,
  value_norm TEXT NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clte, branch_key, type, value_norm)
);

CREATE INDEX IF NOT EXISTS idx_contact_type ON contact (type);
CREATE INDEX IF NOT EXISTS idx_contact_value ON contact (value_norm);

CREATE TABLE IF NOT EXISTS social (
  id BIGSERIAL PRIMARY KEY,
  clte BIGINT NOT NULL REFERENCES company(clte) ON DELETE CASCADE,
  network TEXT NOT NULL,
  url TEXT NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clte, url)
);

CREATE TABLE IF NOT EXISTS category (
  cat_id BIGINT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS company_category (
  clte BIGINT NOT NULL REFERENCES company(clte) ON DELETE CASCADE,
  cat_id BIGINT NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (clte, cat_id)
);

CREATE TABLE IF NOT EXISTS product (
  id BIGSERIAL PRIMARY KEY,
  clte BIGINT NOT NULL REFERENCES company(clte) ON DELETE CASCADE,
  name TEXT NOT NULL,
  price TEXT,
  image_url TEXT,
  url TEXT,
  sku TEXT DEFAULT '',
  description TEXT DEFAULT '',
  availability TEXT DEFAULT '',
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clte, name)
);

CREATE INDEX IF NOT EXISTS idx_product_sku ON product (sku);

CREATE TABLE IF NOT EXISTS snapshot (
  id BIGSERIAL PRIMARY KEY,
  url_hash TEXT NOT NULL,
  url TEXT NOT NULL,
  kind TEXT NOT NULL,
  http_status INT,
  etag TEXT,
  last_modified TEXT,
  content_sha TEXT,
  raw_path TEXT,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_snapshot_url_hash ON snapshot (url_hash);
CREATE INDEX IF NOT EXISTS idx_snapshot_fetched_at ON snapshot (fetched_at);

CREATE TABLE IF NOT EXISTS crawl_url (
  url_hash TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  kind TEXT NOT NULL,
  priority INT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  last_fetched_at TIMESTAMPTZ,
  next_run_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crawl_url_next ON crawl_url (next_run_at);

CREATE TABLE IF NOT EXISTS change_log (
  id BIGSERIAL PRIMARY KEY,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_change_log_changed_at ON change_log (changed_at);
CREATE INDEX IF NOT EXISTS idx_change_log_entity ON change_log (entity, entity_id);

CREATE TABLE IF NOT EXISTS worker (
  id TEXT PRIMARY KEY,
  hostname TEXT,
  pid INT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed BIGINT NOT NULL DEFAULT 0,
  errors BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS seed (
  id BIGSERIAL PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'listing',
  interval_seconds INT NOT NULL DEFAULT 86400,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dead_letter (
  id BIGSERIAL PRIMARY KEY,
  url TEXT NOT NULL,
  kind TEXT,
  error TEXT,
  attempts INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS setting (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO setting (key, value) VALUES
  ('crawl_rps', '0.15'),
  ('crawl_burst', '1'),
  ('daily_cap', '8000'),
  ('off_peak_only', 'false'),
  ('off_peak_start', '0'),
  ('off_peak_end', '7'),
  ('discovery_enabled', 'true'),
  ('products_enabled', 'true'),
  ('max_pages_per_listing', '50'),
  ('conditional_requests', 'true'),
  ('proxy_rotation_enabled', 'false'),
  ('rotate_user_agents', 'false')
ON CONFLICT (key) DO NOTHING;
