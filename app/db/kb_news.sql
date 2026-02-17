-- kb_news schema for migrations
CREATE TABLE IF NOT EXISTS kb_news (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    ts_pub TIMESTAMP NULL,
    ts_ingest TIMESTAMP NOT NULL DEFAULT NOW(),
    title VARCHAR(512) NOT NULL,
    summary VARCHAR(1024),
    url VARCHAR(512),
    source VARCHAR(128),
    lang VARCHAR(8),
    sentiment DOUBLE PRECISION,
    hash VARCHAR(128) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_kb_news_symbol ON kb_news(symbol);
CREATE INDEX IF NOT EXISTS ix_kb_news_ts_ingest ON kb_news(ts_ingest);
