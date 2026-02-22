-- Run once on first Postgres startup (via docker-entrypoint-initdb.d)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
-- pgvector is available via the pgvector/pgvector image
CREATE EXTENSION IF NOT EXISTS vector;
