#!/bin/sh
# Migrate, then serve. The migration runs in the container that is about to
# serve traffic so a deployment can never start on a schema it was not built
# for; Alembic is idempotent, so a restart is safe.
set -e

# Fail fast on an unusable configuration.
#
# uvicorn's multi-worker supervisor does not exit when the application cannot
# be imported: it sits there, serving nothing and never dying, which is the
# worst thing a container can do because the orchestrator sees neither a
# healthy service nor a crash loop. Importing the settings here turns that into
# an immediate, readable exit.
if ! python -c "from app.settings import settings" ; then
  echo "Configuration is not usable; refusing to start. See the error above." >&2
  exit 1
fi

if [ "${OMICSLAB_SKIP_MIGRATIONS:-false}" != "true" ]; then
  echo "running database migrations"
  alembic upgrade head
fi

# --proxy-headers is required for the rate limiter and the access log to see
# the real client address rather than the reverse proxy's.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${OMICSLAB_WEB_CONCURRENCY:-2}" \
  --proxy-headers \
  --forwarded-allow-ips "${OMICSLAB_FORWARDED_ALLOW_IPS:-*}" \
  --no-access-log
