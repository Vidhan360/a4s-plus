#!/bin/sh
# Creates the dedicated test database used by the backend Pytest suite.
# Runs once, on first initialisation of the Postgres data volume.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  SELECT 'CREATE DATABASE a4s_test ENCODING ''UTF8'' TEMPLATE template0'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'a4s_test')\gexec
SQL