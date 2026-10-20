CREATE TABLE IF NOT EXISTS schema_versions (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id bigint PRIMARY KEY,
    chat_id bigint NOT NULL,
    payload jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    received_at timestamptz NOT NULL DEFAULT now(),
    done_at timestamptz,
    last_error text
);
CREATE INDEX IF NOT EXISTS updates_pending ON telegram_updates (available_at, update_id)
    WHERE done_at IS NULL;
CREATE INDEX IF NOT EXISTS updates_chat ON telegram_updates (chat_id, update_id)
    WHERE done_at IS NULL;

CREATE TABLE IF NOT EXISTS admin_dialogs (
    chat_id bigint PRIMARY KEY,
    user_id bigint NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_update_id bigint NOT NULL UNIQUE REFERENCES telegram_updates(update_id),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    image_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telegram_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_update_id bigint NOT NULL UNIQUE REFERENCES telegram_updates(update_id),
    chat_id bigint NOT NULL,
    payload jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    last_error text
);
CREATE INDEX IF NOT EXISTS outbox_pending ON telegram_outbox (available_at, id)
    WHERE sent_at IS NULL;
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
