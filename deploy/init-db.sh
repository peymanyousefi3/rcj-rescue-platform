#!/bin/sh
# Runs only when initializing a NEW database volume. Existing installations use the upgrade guide.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$APP_DB_PASSWORD" --set=admin_role="$POSTGRES_USER" <<'SQL'
CREATE ROLE arena_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE arena TO arena_app;
GRANT USAGE ON SCHEMA public TO arena_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO arena_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO arena_app;
SQL
