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
6. Nothing to set for ports. `docker-compose.yml` publishes no host port: the
   proxy reaches `web` over the Docker network, so the deployment cannot
   collide with another app's port and nothing bypasses TLS. Local runs get
   `localhost:8080` from `docker-compose.override.yml`, which `docker compose
   up` merges on its own and Coolify's `-f docker-compose.yml` skips.
7. Keep one `api` replica (see "Scaling" below) and give the server at least
   4 GB of memory: the science image builds Scanpy, and a Core run holds its
   matrix in memory.
8. After the first successful deploy, seed the launch content once from the
   `api` container's terminal in Coolify. Pass the admin password inline so it
   never sits in the service's environment; it must meet the password policy:

       OMICSLAB_ADMIN_EMAIL=you@example.org OMICSLAB_ADMIN_PASSWORD='…' python scripts/seed.py

   This creates the administrator, the guided dataset records (awaiting their
   files) and the two labelled synthetic fixtures. Running it again changes
   nothing that already exists.
9. Optional, same terminal: `python scripts/fetch_gene_sets.py` installs the
   locked Hallmark gene sets and `python scripts/fetch_interactions.py` the
   ligand-receptor database. Without them, pathway enrichment and the
   communication module stop with a message naming the missing asset.

Locally the same topology runs with:

    cp .env.example .env      # then fill in the two secrets
    docker compose up --build

## Scientific runtimes

`INCLUDE_SCIENCE=false` builds a small API image with the Foundation numerics
only. The Core and Advanced pipelines then fail with a message naming the
missing method — they are never silently substituted, because the method
version stamped on a run has to be true. Set `INCLUDE_SCIENCE=true` to build
Scanpy (and its Scrublet), leidenalg, umap-learn and GSEApy into the image;
expect roughly triple the image size and build time. The same flag brings in
anndata and h5py, which the ingestion readers need for `.h5ad` and 10x `.h5`.

The adapters check the installed release against the lock rather than trusting
it: a umap-learn or DESeq2 that differs from [method-lock.md](method-lock.md)
refuses to run, with the two versions named.

DESeq2 (Foundation differential expression) needs R, Bioconductor and rpy2 in
the API process. **This repository does not yet build that R image.** Until one
is provisioned, a Foundation run stops at differential expression with a
message saying so; every earlier Foundation step runs. Pinning the R image to
DESeq2 1.42.0 (Bioconductor 3.18) is a decision for the method owner, because
the version stamped on every Foundation run follows from it.

## Ingesting the guided datasets

The guided datasets are seeded as `pending_data_ingest` and stay unavailable
until an operator ingests them. The download is deliberately a person's step:
each accession carries terms of use someone has to accept. Once the files are
on disk, copy them into the API container and run the ingestion script there
(it is in the image, and writes to the `/data` volume):

    docker compose cp ./pbmc api:/tmp/pbmc
    docker compose exec api python scripts/fetch_guided_data.py \
        pbmc-interferon-beta /tmp/pbmc/filtered_feature_bc_matrix \
        --metadata /tmp/pbmc/cells.csv --min-cells-per-gene 3 --max-cells 12000 --seed 0

`python scripts/fetch_guided_data.py --help` lists every option; the header of
the script has the command for each guided dataset. What it accepts and does:

| Input | Read as |
|---|---|
| CSV / TSV (optionally `.gz`) | genes × samples for Foundation; the axis carrying the metadata's identifiers is the observation axis |
| 10x directory or `matrix.mtx(.gz)` + features + barcodes | only Gene Expression features are kept; gene symbols, not IDs |
| 10x `.h5` | Cell Ranger 2 and 3 layouts |
| `.h5ad` | the first of the `counts` layer, `.raw`, `.X` that holds raw counts; coordinates from `obsm['spatial']` |
| Space Ranger `outs/` | the filtered matrix plus `spatial/tissue_positions.csv`; spots outside the tissue are dropped |

- Metadata is matched to the matrix **by identifier, never by row order**
  (`sample_id`; `cell_id` or `barcode`; `spot_id` or `barcode`). A matrix
  column with no metadata row is refused.
- Only **raw counts** are accepted. Normalised or log values are refused, not
  converted: the locked methods model counts.
- The analysis object is **dense in memory**. Past 250 million values the
  ingestion is refused unless you reduce it: `--min-cells-per-gene` drops rarely
  detected genes and `--max-cells` takes a seeded subsample. Both are recorded
  on the dataset, and a subsample is added to its limitations, so every result
  and report says it describes a subsample.
- `--set FIELD=VALUE` gives every observation an annotation it lacks — for a
  single Visium section, `--set sample_id=section1 --set condition=reference`.

The Expert upload reads files through the same code, so a format means the same
thing on both routes.

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

### Opening the paid features for testing

`OMICSLAB_OPEN_ACCESS_TIER` sets the tier the shared session holds. It defaults
to `basic`, which is what a real learner gets and the only correct value for
anything the public can reach. Raise it to `moderate` or `expert` on an
evaluation or development deployment and every paid feature opens — upload,
compare runs, the communication explorer, the spatial workflow, the capstone.

It is a **grant, not a bypass**: the shared account simply holds a higher
entitlement, and every server-side check runs against it exactly as it always
does. Nothing in the entitlement matrix is skipped, so what you are testing is
the real gating logic rather than a disabled version of it.

Two consequences worth stating. It applies only to the shared open-access
account — a registered learner's tier still comes from their own entitlements,
which is asserted by a test. And it takes effect when a session is issued, in
both directions: raising it grants the tier, and lowering it (back to `basic`,
say) revokes that grant, the next time any browser opens a new session. Open
the site once in a private window after changing the variable, and every
browser sharing the account sees the new tier on its next reload.

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
- **An upload is private to the learner who uploaded it.** It is absent from
  everyone else's dataset list, inspector, runs and spatial reference choices
  (they get a 404, so its existence is not disclosed either). The shared
  open-access session is one account, so in that mode everyone shares it.

## Running a cohort from the admin console

The console at `/admin` opens for administrator accounts only; the open-access
session is a learner and is told so.

- **Cohorts and week unlock.** The eight weeks open progressively. Move a
  cohort to a week, or one learner for a late start or a deferral. Moving back
  never deletes work.
- **Commercial terms.** Price, currency and term per paid tier, and the run and
  what-if allowance per tier, are admin settings rather than code (spec 12).
  They are validated: Basic is never priced, Basic always keeps at least one run
  and one what-if, and a higher tier never gets less than a lower one. A price
  or term change applies to new orders only.
- **Learner-reported issues.** "Report an issue" in the footer captures the
  screen, and on a run's page the run, so a report can be reproduced. Triage
  them here: open, acknowledged, resolved, with a note to the record.
- **Learner completion.** Per learner: week, completed runs and the weeks they
  cover, interpretations, pre-lab and week assessments, capstone and defence
  score.

