#!/bin/sh
# Se ejecuta una sola vez, al inicializar un volumen de Postgres vacío
# (docker-entrypoint-initdb.d). Postgres no permite que el usuario bootstrap
# (POSTGRES_USER) se quite SUPERUSER a sí mismo ("the bootstrap user must
# have the SUPERUSER attribute"), así que en vez de intentarlo se crea un
# segundo rol sin privilegios elevados -- app_runtime -- y la aplicación se
# conecta con ese, nunca con el bootstrap.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE app_runtime WITH LOGIN PASSWORD '$POSTGRES_PASSWORD'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO app_runtime;
    GRANT ALL ON SCHEMA public TO app_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_runtime;
EOSQL
