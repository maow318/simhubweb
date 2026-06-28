CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    carrier TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    flag TEXT NOT NULL DEFAULT '🌐',
    card_background_asset_name TEXT,
    card_color_hex TEXT,
    card_background_image_data TEXT,
    carrier_app_icon_url_string TEXT,
    carrier_app_store_url_string TEXT,
    carrier_app_name TEXT,
    activation_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    price TEXT NOT NULL DEFAULT '',
    currency_code TEXT,
    cycle_payment_minor_units INTEGER,
    current_balance_minor_units INTEGER,
    website_url TEXT,
    current_balance TEXT,
    transaction_notes TEXT,
    custom_prompt TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    order_index INTEGER NOT NULL DEFAULT 0,
    smdp_address TEXT NOT NULL DEFAULT '',
    activation_code TEXT NOT NULL DEFAULT '',
    confirmation_code TEXT,
    eid TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_long_term INTEGER NOT NULL DEFAULT 0,
    reminder_mode TEXT NOT NULL DEFAULT 'default',
    reminder_days_before INTEGER,
    operation_reminder_enabled INTEGER NOT NULL DEFAULT 0,
    operation_date TEXT,
    operation_days_before_expiry INTEGER,
    operation_note TEXT,
    renew_days INTEGER NOT NULL DEFAULT 30,
    renewal_unit TEXT,
    renewal_interval_value INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cards_expiry ON cards(expiry_date);
CREATE INDEX IF NOT EXISTS idx_cards_country ON cards(country_name);
CREATE INDEX IF NOT EXISTS idx_cards_order ON cards(order_index);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT,
    card_label TEXT,
    action TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    smtp_host TEXT NOT NULL DEFAULT '',
    smtp_port INTEGER NOT NULL DEFAULT 465,
    smtp_username TEXT NOT NULL DEFAULT '',
    smtp_password TEXT NOT NULL DEFAULT '',
    recipient TEXT NOT NULL DEFAULT '',
    twofa_enabled INTEGER NOT NULL DEFAULT 0,
    twofa_method TEXT NOT NULL DEFAULT 'email',
    reminder_enabled INTEGER NOT NULL DEFAULT 0,
    reminder_days_before INTEGER NOT NULL DEFAULT 3,
    last_reminder_date TEXT NOT NULL DEFAULT '',
    tg_enabled INTEGER NOT NULL DEFAULT 0,
    tg_token TEXT NOT NULL DEFAULT '',
    tg_chat_id TEXT NOT NULL DEFAULT '',
    tg_reminder_enabled INTEGER NOT NULL DEFAULT 0,
    tg_days_before INTEGER NOT NULL DEFAULT 3,
    webhook_enabled INTEGER NOT NULL DEFAULT 0,
    webhook_url TEXT NOT NULL DEFAULT '',
    webhook_method TEXT NOT NULL DEFAULT 'POST',
    webhook_headers TEXT NOT NULL DEFAULT '',
    webhook_payload TEXT NOT NULL DEFAULT '',
    webhook_days_before INTEGER NOT NULL DEFAULT 3,
    last_reminder_scan_at TEXT NOT NULL DEFAULT '',
    last_reminder_scanned INTEGER NOT NULL DEFAULT 0,
    last_reminder_matched INTEGER NOT NULL DEFAULT 0,
    last_reminder_sent INTEGER NOT NULL DEFAULT 0,
    last_reminder_failed INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS reminder_log (
    card_id TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'expiry',
    sent_date TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'email',
    PRIMARY KEY (card_id, event_type, sent_date, channel)
);

CREATE TABLE IF NOT EXISTS reminder_attempt_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT,
    card_label TEXT,
    event_type TEXT NOT NULL DEFAULT 'expiry',
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    sent_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reminder_attempt_log_created ON reminder_attempt_log(created_at);
CREATE INDEX IF NOT EXISTS idx_reminder_attempt_log_card ON reminder_attempt_log(card_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ts ON login_attempts(ip, ts);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ts ON login_attempts(ts);
