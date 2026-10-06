#!/bin/sh
set -eu

python -m alembic upgrade head
# The HTTP process does not need schema-owner credentials.
unset MIGRATION_DATABASE_URL
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
