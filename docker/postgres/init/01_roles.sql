-- 01_roles.sql
-- Create roles and set connection parameters

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ontoagent_ro') THEN
    CREATE ROLE ontoagent_ro WITH LOGIN PASSWORD 'ro_secret';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ontoagent_kb') THEN
    CREATE ROLE ontoagent_kb WITH LOGIN PASSWORD 'kb_secret';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ontoagent_app') THEN
    CREATE ROLE ontoagent_app WITH LOGIN PASSWORD 'app_secret';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ontoagent_ops') THEN
    CREATE ROLE ontoagent_ops WITH LOGIN PASSWORD 'ops_secret';
  END IF;
END $$;

-- ontoagent_ro settings
ALTER ROLE ontoagent_ro SET default_transaction_read_only = on;
ALTER ROLE ontoagent_ro SET statement_timeout = '5s';

-- Create schemas
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS kb;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS checkpoint;

-- Base schema usage
GRANT USAGE ON SCHEMA analytics TO ontoagent_ro, ontoagent_app, ontoagent_ops;
GRANT USAGE ON SCHEMA kb TO ontoagent_kb;
GRANT USAGE ON SCHEMA ops TO ontoagent_app, ontoagent_ops;

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
