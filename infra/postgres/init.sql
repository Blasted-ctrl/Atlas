-- Atlas PostgreSQL Initialization Script
-- Enables required extensions for the platform

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Set default search path
ALTER DATABASE atlas SET search_path TO public;
