# OmicsLab Pro

The Live Lab platform for NanoSchool's eight-week single-cell and spatial
transcriptomics flagship program.

All three build phases are implemented (`ACTIVE_PHASE = 3`):

- **Phase 1 — Launch Core (Basic, free with enrollment).** Authentication with
  Basic auto-granted, the Knowledge Bank, the Week 1 Experimental Design Studio,
  the guided Foundation and Core pipelines, the Omics Copilot, one perturbation
  type, summary reports, the admin console.
- **Phase 2 — Moderate (paid).** Trial datasets, independent reruns, wider
  parameter ranges, the Cell-Cell Communication Explorer, the full spatial
  workflow, Compare Runs, full exports, and the purchase and activation flow.
- **Phase 3 — Expert (premium).** Analysis-ready dataset upload, custom design
  formulas and contrasts, extended spatial and reference options, self-authored
  perturbations, and the capstone workspace with its figure pack and defence
  deck.

The phase gate is still live and still tested, so a future module can be
declared before it is routable. Raw sequencing processing is deliberately not
scaffolded: it stays behind a separate compute, storage and security sign-off,
and the ingestion validator rejects raw formats outright.

## The two vocabularies

| Dimension | Labels |
|---|---|
| Scientific analysis track | **Foundation** (Bulk RNA-seq) / **Core** (scRNA-seq) / **Advanced** (Spatial) |
| Commercial access tier | **Basic** / **Moderate** / **Expert** |

They never mix. See [docs/naming-rule.md](docs/naming-rule.md); the rule is
enforced by a linter that runs inside the test suite.

## Layout

    backend/app/constants.py          the two enums, locked methods, active phase
    backend/app/core/entitlements.py  the Feature Entitlement Matrix (single source of truth)
    backend/app/core/parameters.py    the parameter registry (no thresholds live anywhere else)
    backend/app/copilot/              Copilot: evidence registry, grounding guard, knowledge, labels, perturbation
    backend/app/pipelines/            step graphs (foundation, core, advanced, communication),
                                      reference numerics, locked-method adapters, runner
    backend/app/governance/           ingestion gates and the validated-object loader
    backend/app/api/routers/          the API behind the thirteen screens
    frontend/src/pages/               the thirteen screens, each a first-class route
    scripts/lint_naming.py            the Section 14 guardrail linter
    docs/method-lock.md               frozen method choices and SME sign-off state
    docs/phase-2-3-definition-of-done.md   what Phases 2 and 3 do and do not deliver

## Deploying it

Three containers — Postgres, the API, and nginx serving the built front end and
proxying `/api` to the API, so the browser only ever sees one origin:

    cp .env.example .env      # fill in OMICSLAB_JWT_SECRET and POSTGRES_PASSWORD
    docker compose up --build

The API refuses to start in production with the development signing key, a key
shorter than 32 characters, or a wildcard CORS origin. Migrations run in the
container before it serves traffic. Full instructions, including the Coolify
setup and the one hard scaling limit, are in
[docs/deployment.md](docs/deployment.md).

## Running it in development

This is a two-part project: a Python API in `backend/` and a Vite React app in
`frontend/`. The root `package.json` is a task runner that delegates to both, so
every command below is run from the repository root.

First time:

    python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
    npm run install:frontend
    npm run seed

Then start both halves, in two terminals:

    npm run dev:api    # FastAPI on :8000
    npm run dev        # Vite on :5173, proxying /api to :8000

The front end needs the API running: it proxies `/api` to port 8000, so starting
`npm run dev` alone gives you a page that cannot load anything.

Tests and guardrails:

    npm test           # or: PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
    npm run lint       # the naming-rule and parameter-registry guardrails
    npm run typecheck  # the front end

CI runs all of the above, builds both images, checks that the Alembic
migrations still match the models, and asserts that the API image refuses an
unsafe production configuration.

## Access

`OMICSLAB_OPEN_ACCESS` defaults to **true**: the lab opens directly into the
workspace with no sign-in and no sign-out control, on one shared Basic-tier
account. That means every visitor shares one workspace and can see each other's
runs — an evaluation mode, not a multi-tenant one. The credential path is fully
implemented and tested underneath; set the variable to `false` to put the
sign-in screen back in front of the app.

## How a run executes

A pipeline run is **not** executed inside the HTTP request that creates it. The
API validates the request, records the run, and returns it as `queued`; the
pipeline then executes on an in-process worker pool while the workspace polls
the run record. A real Core or Advanced run takes minutes, and holding a
connection open for that long means a proxy eventually times it out and the
learner sees a network error for a run that is actually still going.

Two consequences worth knowing before scaling:

  * Run capacity scales with `OMICSLAB_RUN_WORKER_THREADS`, not with web
    workers or replicas. Keep the API at one replica until `jobs.submit` is
    moved onto a real queue — status already lives in the database, so nothing
    else would need to change.
  * On boot, any run still claiming to be queued or running is closed out as
    failed with an explanation: it died with the process executing it, and
    showing it as in progress forever would be a lie.

## Scientific tracks and modules

| Track | Pipeline | Version |
|---|---|---|
| Foundation — Bulk RNA-seq | `pipelines/foundation.py` | `foundation-1.0.0` |
| Core — single-cell RNA-seq | `pipelines/core.py` | `core-1.0.0` |
| Advanced — spatial transcriptomics | `pipelines/advanced.py` | `advanced-1.0.0` |

The Cell-Cell Communication Explorer (`pipelines/communication.py`,
`communication-1.0.0`) is an extension module that runs on Core data. It repeats
the Core preparation steps rather than reading another run's state, so a
communication run is reconstructable on its own, and it is versioned separately
so revising it never silently revises a guided Core run.

## Scientific runtimes

`backend/requirements.txt` runs the API. The locked scientific runtimes live in
`backend/requirements-science.txt` (Scanpy, leidenalg, GSEApy) plus a separate R
worker image carrying Bioconductor and DESeq2. When a locked runtime is absent,
the run fails with a message naming the missing method — it is never silently
substituted, because the method version stamped on a run must be true.

The `leidenalg` and `igraph` packages are needed for the Core pipeline to
complete; without them clustering fails cleanly and the earlier steps' results
are preserved.

## Data

Guided teaching datasets (GSE52778, GSE96583, and a Visium section) are seeded
with full provenance but as `pending_data_ingest`: they are not selectable until
an operator runs `scripts/fetch_guided_data.py`, which validates them through the
same governance gate as any upload. No placeholder results stand in for missing
teaching data.

Two curated external assets are fetched separately and are not bundled, because
their licences do not permit redistribution:

    python scripts/fetch_gene_sets.py     h.all.v2023.2.Hs.symbols.gmt
    python scripts/fetch_interactions.py  interaction_input.csv

Without them, pathway enrichment and the communication module fail with a
message naming the missing asset rather than substituting another.

`scripts/seed.py` writes two synthetic development fixtures — one single-cell,
one spatial — labelled as synthetic in their name, provenance and limitations, so
the workflows can be exercised locally. Every result computed from them is
biologically meaningless by construction.

## Scientific rules the code enforces

These are enforced by the pipelines and the registry, not by interface copy, so
no screen or export can present a result without the limitation attached to it:

- Condition inference is always sample-aware. `sc.de.grouping` is single-valued
  at every tier and is absent from the perturbation whitelist, so no tier and no
  self-authored what-if can reach cell-level condition testing.
- Spatial outputs stamp their own `inference_scope`. A single-specimen package
  makes every region comparison descriptive and hypothesis-generating, and the
  Copilot's label rules downgrade conclusions drawn from it.
- Deconvolution output carries `estimate_kind = "compositional"` and
  `per_spot_identity = False`. A spot estimate is never a single-cell identity.
- Communication output carries `evidenceKind =
  "inferred_candidate_communication"`, and every candidate mechanism states the
  perturbation experiment that would be needed to confirm it.
- Spatial neighbourhood geometry must match the capture platform. Ring adjacency
  uses true hex distance, and asking for grid geometry on a package with no array
  positions fails rather than silently using a distance rule.

## What the Copilot can and cannot do

The Copilot is the mentor and interpretation layer, never the statistical engine.
Its responses are composed from reviewed knowledge whose only variable content is
a *reference* — `{{computed:...}}`, `{{param:...}}`, `{{method:...}}` — resolved
from the actual run. A verifier then re-reads the finished text and rejects any
number or gene-shaped token that did not arrive through one of those references,
and any citation outside the approved evidence registry. A template with a
hard-typed result in it therefore cannot ship: the test suite renders every
knowledge entry through the same guard.
