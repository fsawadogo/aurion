#!/usr/bin/env sh
# Container entrypoint: bring the schema current, then exec the app.
#
# Migrations run synchronously before uvicorn starts so the lifespan
# startup hooks (seed_dev_users, AppConfig polling) see a ready schema.
# If migrations fail, the container exits non-zero — compose marks the
# service unhealthy instead of serving 500s.

set -eu

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] exec $*"
exec "$@"
