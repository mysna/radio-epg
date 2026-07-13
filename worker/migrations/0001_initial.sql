PRAGMA foreign_keys = ON;

CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(trim(name)) > 0),
  kind TEXT NOT NULL CHECK (length(trim(kind)) > 0),
  base_url TEXT NOT NULL CHECK (length(trim(base_url)) > 0),
  priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
  terms_note TEXT,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE image_assets (
  id TEXT PRIMARY KEY,
  source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('broadcaster', 'channel', 'program')),
  entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
  content_hash TEXT NOT NULL UNIQUE CHECK (length(trim(content_hash)) > 0),
  rights_status TEXT NOT NULL DEFAULT 'unknown',
  source_url TEXT NOT NULL CHECK (length(trim(source_url)) > 0),
  source_page_url TEXT NOT NULL CHECK (length(trim(source_page_url)) > 0),
  author TEXT,
  license TEXT,
  attribution TEXT,
  available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
  first_verified_at TEXT NOT NULL,
  last_verified_at TEXT NOT NULL,
  UNIQUE (entity_type, entity_id, content_hash)
);

CREATE TABLE broadcasters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(trim(name)) > 0),
  homepage_url TEXT,
  image_asset_id TEXT REFERENCES image_assets(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE channels (
  id TEXT PRIMARY KEY,
  broadcaster_id TEXT NOT NULL REFERENCES broadcasters(id) ON DELETE RESTRICT,
  name TEXT NOT NULL CHECK (length(trim(name)) > 0),
  region_id TEXT,
  stn TEXT NOT NULL CHECK (length(trim(stn)) > 0),
  ch TEXT,
  city TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  image_asset_id TEXT REFERENCES image_assets(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE channel_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  alias_type TEXT NOT NULL CHECK (alias_type IN ('radio_id', 'tuple', 'legacy')),
  alias_value TEXT NOT NULL CHECK (length(trim(alias_value)) > 0),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (alias_type, alias_value)
);

CREATE TABLE programs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  upstream_id TEXT NOT NULL CHECK (length(trim(upstream_id)) > 0),
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  description TEXT,
  hosts_json TEXT,
  genre TEXT,
  homepage_url TEXT,
  image_asset_id TEXT REFERENCES image_assets(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (source_id, upstream_id)
);

CREATE TABLE schedule_events (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE CHECK (length(trim(event_key)) > 0),
  channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE RESTRICT,
  program_id TEXT REFERENCES programs(id) ON DELETE SET NULL,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  source_event_id TEXT,
  broadcast_date TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  subtitle TEXT,
  is_live INTEGER NOT NULL DEFAULT 0 CHECK (is_live IN (0, 1)),
  is_rerun INTEGER NOT NULL DEFAULT 0 CHECK (is_rerun IN (0, 1)),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  source_url TEXT NOT NULL CHECK (length(trim(source_url)) > 0),
  source_kind TEXT NOT NULL CHECK (length(trim(source_kind)) > 0),
  fetched_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (ends_at > starts_at),
  UNIQUE (source_id, source_event_id)
);

CREATE TABLE scrape_runs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  idempotency_key TEXT NOT NULL UNIQUE CHECK (length(trim(idempotency_key)) > 0),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'partial')),
  channel_count INTEGER NOT NULL DEFAULT 0 CHECK (channel_count >= 0),
  program_count INTEGER NOT NULL DEFAULT 0 CHECK (program_count >= 0),
  event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
  image_count INTEGER NOT NULL DEFAULT 0 CHECK (image_count >= 0),
  error_summary TEXT,
  artifact_key TEXT
);

CREATE TABLE image_variants (
  asset_id TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  variant_name TEXT NOT NULL CHECK (variant_name IN ('small', 'medium', 'original')),
  mime_type TEXT NOT NULL CHECK (length(trim(mime_type)) > 0),
  width INTEGER NOT NULL CHECK (width > 0),
  height INTEGER NOT NULL CHECK (height > 0),
  byte_size INTEGER NOT NULL CHECK (byte_size > 0),
  r2_key TEXT NOT NULL UNIQUE CHECK (length(trim(r2_key)) > 0),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (asset_id, variant_name)
);

CREATE TABLE image_takedowns (
  id TEXT PRIMARY KEY,
  asset_id TEXT REFERENCES image_assets(id) ON DELETE SET NULL,
  content_hash TEXT,
  source_url TEXT,
  reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  requested_at TEXT NOT NULL,
  completed_at TEXT,
  permanent_block INTEGER NOT NULL DEFAULT 1 CHECK (permanent_block IN (0, 1)),
  CHECK (
    (content_hash IS NOT NULL AND length(trim(content_hash)) > 0)
    OR (source_url IS NOT NULL AND length(trim(source_url)) > 0)
  )
);

CREATE INDEX idx_channel_aliases_channel ON channel_aliases(channel_id);
CREATE INDEX idx_programs_source ON programs(source_id);
CREATE INDEX idx_schedule_events_channel_starts ON schedule_events(channel_id, starts_at);
CREATE INDEX idx_schedule_events_channel_date ON schedule_events(channel_id, broadcast_date);
CREATE INDEX idx_schedule_events_source_scope ON schedule_events(source_id, channel_id, broadcast_date);
CREATE INDEX idx_scrape_runs_source_started ON scrape_runs(source_id, started_at);
CREATE INDEX idx_image_assets_entity ON image_assets(entity_type, entity_id);
CREATE INDEX idx_image_takedowns_hash ON image_takedowns(content_hash);
CREATE INDEX idx_image_takedowns_source_url ON image_takedowns(source_url);
