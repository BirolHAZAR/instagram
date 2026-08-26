#!/bin/sh
set -e

mkdir -p /app/runtime/celerybeat /app/media /app/staticfiles

if [ -n "$DB_HOST" ]; then
  until nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
    echo "Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}..."
    sleep 1
  done
fi

if [ -n "$REDIS_HOST" ]; then
  until nc -z "$REDIS_HOST" "${REDIS_PORT:-6379}"; do
    echo "Waiting for Redis at $REDIS_HOST:${REDIS_PORT:-6379}..."
    sleep 1
  done
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${COLLECTSTATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
