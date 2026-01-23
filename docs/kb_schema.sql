-- Knowledge Base schema (versioned, topic/year aware)
-- Safe to run multiple times (IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS kb_topics (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,
    topic TEXT,
    year INT,
    lang TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_versions (
    id SERIAL PRIMARY KEY,
    doc_id INT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    version INT NOT NULL,
    valid_from TIMESTAMPTZ DEFAULT now(),
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN DEFAULT TRUE,
    UNIQUE(doc_id, version)
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id SERIAL PRIMARY KEY,
    doc_id INT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    version_id INT NOT NULL REFERENCES kb_versions(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    chunk_year INT,
    topic TEXT,
    lang TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(chunk_hash, doc_id, version_id)
);

-- Embeddings table stores only metadata; vector index can live in FAISS/SQLite.
CREATE TABLE IF NOT EXISTS kb_embeddings (
    chunk_id INT PRIMARY KEY REFERENCES kb_chunks(id) ON DELETE CASCADE,
    model TEXT,
    dim INT,
    stored_at TIMESTAMPTZ DEFAULT now()
);

