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
    renew_days INTEGER NOT NULL DEFAULT 30,
    renewal_unit TEXT,
    renewal_interval_value INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cards_expiry ON cards(expiry_date);
CREATE INDEX IF NOT EXISTS idx_cards_country ON cards(country_name);
CREATE INDEX IF NOT EXISTS idx_cards_order ON cards(order_index);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE
);
