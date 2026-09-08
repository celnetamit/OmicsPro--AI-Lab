# Deploying OmicsLab Pro

Three containers: Postgres, the API, and nginx serving the built front end and
proxying `/api` to the API. The browser therefore only ever talks to one origin,
so no CORS configuration stands between a learner and their work.

    browser ──▶ web (nginx :8080) ──┬──▶ /            static React bundle
                                    └──▶ /api/*  ──▶  api (uvicorn :8000) ──▶ db (Postgres)

## Before the first deploy

Generate the signing key and the database password:

    openssl rand -hex 32      # OMICSLAB_JWT_SECRET
    openssl rand -hex 24      # POSTGRES_PASSWORD

The API **refuses to start** in production with the development signing key, a
key shorter than 32 characters, or a wildcard CORS origin. The container exits
immediately with the reason on stderr rather than lingering: uvicorn's worker
supervisor will otherwise sit there serving nothing and never exiting, which
shows up as a service that is neither healthy nor crash-looping. That is deliberate:
a JWT signed with a key that ships in the repository is forgeable by anyone who
can read the source.

The Postgres volume keeps whatever password it was first initialised with.
Changing `POSTGRES_PASSWORD` later does nothing until the volume is recreated.

## Coolify

1. New resource → Docker Compose, pointed at this repository.
2. Set the environment variables from [`.env.example`](../.env.example).
   `OMICSLAB_JWT_SECRET` and `POSTGRES_PASSWORD` are required.
3. Set `OMICSLAB_RELEASE` as a **build variable**. The build context contains no
   `.git`, so the image cannot report its own commit; this is the only way the
   running deployment can be identified.
4. Point the domain at the `web` service, port 8080. Let Coolify terminate TLS.
5. Set `INCLUDE_SCIENCE=true` unless the deployment serves the Foundation track
   only — see "Scientific runtimes" below.

Locally the same topology runs with:

    cp .env.example .env      # then fill in the two secrets
    docker compose up --build

## Scientific runtimes

`INCLUDE_SCIENCE=false` builds a small API image with the Foundation numerics
only. The Core and Advanced pipelines then fail with a message naming the
missing method — they are never silently substituted, because the method
version stamped on a run has to be true. Set `INCLUDE_SCIENCE=true` to build
Scanpy, leidenalg and GSEApy into the image; expect roughly triple the image
size and build time.

DESeq2 runs in a separate R worker image (see [method-lock.md](method-lock.md)).

## Migrations

The API container runs `alembic upgrade head` before serving, so a deployment
can never start against a schema it was not built for. Alembic is idempotent, so
restarts and replicas are safe. Set `OMICSLAB_SKIP_MIGRATIONS=true` only when
migrating out of band.

To add a migration after changing a model:

    cd backend
    PYTHONPATH=. alembic revision --autogenerate -m "what changed"
    PYTHONPATH=. alembic upgrade head

CI fails if the models and the migrations have drifted apart.

## Scaling, and its one hard limit

Pipeline runs execute on an in-process thread pool
(`OMICSLAB_RUN_WORKER_THREADS`), not inside the HTTP request. Two consequences:

- **Keep `OMICSLAB_WEB_CONCURRENCY` at 1, and run a single API replica.** Run
  capacity scales with worker threads, not with web workers or replicas.
- Scaling out horizontally means moving `app/core/jobs.submit` onto a real
  queue. Nothing else changes: run status already lives in the database, which
  is why the workspace can poll it and why a restart can recover.

On boot, any run still claiming to be queued or running is closed out as failed
with an explanation — it died with the process that was executing it, and
showing it as in progress forever would be a lie.

Rate limiting is likewise in-process: with N replicas the effective limit is N
times the configured one. It exists to blunt credential stuffing, not to meter
a public API.

## What to watch

| Signal | Where |
|---|---|
| Liveness | `GET /api/health` — does not touch the database, so a database blip does not get the process killed |
| Readiness | `GET /api/health/ready` — 503 when the database is unreachable; reports `runsInFlight` |
| Logs | JSON lines on stdout (`OMICSLAB_LOG_JSON=false` for human-readable), every line carrying `requestId` |
| A learner's bug report | Errors show a reference; it is the `requestId` in the log |

## Open access

`OMICSLAB_OPEN_ACCESS` is **true**, so the Live Lab opens straight into the
workspace: no sign-in screen, and no sign-out control. A visitor is signed in
to one shared, enrolled, Basic-tier account (`OMICSLAB_GUEST_EMAIL`) issued by
`POST /api/auth/guest`. Every run, interpretation and report still belongs to a
real user, because the whole record model is per-user; the account's password
is random and never issued, so it cannot be logged into.

What this means while it is on:

- **Everyone shares one workspace.** Any visitor sees and can act on the runs,
  interpretations and reports any other visitor created. It is a demonstration
  and evaluation mode, not a multi-tenant one.
- Registration and login still work and are still tested; they are simply not
  the entry point.

Set `OMICSLAB_OPEN_ACCESS=false` to put the sign-in screen back in front of the
app. Nothing else changes: the guest endpoint starts returning 404, the client
falls through to the sign-in screen, and the sign-out control returns.

## Operational facts worth knowing before launch

- **Tokens cannot be revoked.** Signing out discards the token client-side; the
  token itself stays valid until it expires (`OMICSLAB_ACCESS_TOKEN_TTL_MINUTES`,
  12 hours by default). Changing a password does not invalidate issued tokens.
  Shorten the TTL if that trade is unacceptable.
- **No payment provider is wired in.** `POST /api/billing/checkout` records an
  order as `awaiting_payment`; an administrator activates it once payment is
  confirmed out of band. `_charge` is the seam a provider integration replaces.
- **Uploaded datasets and guided data live on a volume** (`/data`). It is not
  backed up by anything in this repository. Back up the Postgres volume and the
  data volume together: a run record without its dataset is not reconstructable.
- **Raw sequencing processing is deliberately absent.** The ingestion validator
  rejects raw formats outright; it stays behind a separate compute, storage and
  security sign-off.
