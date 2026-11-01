CREATE TABLE IF NOT EXISTS contact_messages (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    phone VARCHAR(30) NOT NULL,
    email VARCHAR(254) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'Aberto',
    priority VARCHAR(20) NOT NULL DEFAULT 'Normal',
    ip_address INET,
    user_agent VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_messages_created_at
    ON contact_messages (created_at DESC);

-- Agenda times are local wall-clock values in America/Sao_Paulo.
-- Contact snapshots are intentionally independent of deletions in the inbox.
CREATE TABLE IF NOT EXISTS agenda_events (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(160) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    start_at VARCHAR(16) NOT NULL,
    end_at VARCHAR(16) NOT NULL,
    location VARCHAR(180) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    contacts_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS idx_agenda_start_at ON agenda_events (start_at);

CREATE TABLE IF NOT EXISTS mural_click_logs (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL UNIQUE,
    video_id BIGINT NOT NULL,
    video_title VARCHAR(500) NOT NULL,
    source VARCHAR(20) NOT NULL CHECK (source IN ('carousel', 'catalog', 'player')),
    ip_address VARCHAR(45) NOT NULL,
    clicked_at VARCHAR(32) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mural_logs_time ON mural_click_logs (clicked_at);
CREATE INDEX IF NOT EXISTS idx_mural_logs_video ON mural_click_logs (video_id, clicked_at);
CREATE INDEX IF NOT EXISTS idx_mural_logs_ip ON mural_click_logs (ip_address, clicked_at);

CREATE TABLE IF NOT EXISTS admin_credentials (
    username VARCHAR(120) PRIMARY KEY,
    password_hash TEXT NOT NULL,
    credential_version VARCHAR(36) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Deny public Data API access without policies. The server's database owner
-- connection continues to work; Supabase anon keys are not used by this app.
ALTER TABLE contact_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agenda_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE mural_click_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_credentials ENABLE ROW LEVEL SECURITY;
