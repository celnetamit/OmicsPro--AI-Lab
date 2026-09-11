# Locked scientific methods

Every entry in `LOCKED_METHODS` (`backend/app/constants.py`) is a frozen choice.
Changing one is a versioned code change, never a runtime setting, so the method
version recorded against every historical run stays true.

Two kinds of lock appear below, and the distinction matters:

- **External runtime** — the method lives in a third-party package. Its adapter
  in `backend/app/pipelines/locked.py` raises `BackendUnavailable` if that
  runtime is absent. It is never approximated in-house.
- **Validated in-pipeline** — the method is an exactly specified statistic
  computed inside this codebase. The lock records that honestly rather than
  naming a package the run never touched. Where such a method reads a curated
  external asset (gene sets, ligand-receptor pairs), that asset is itself
  version-locked and fetched by a script.

| Area | Locked choice | Version | Kind | Status |
|---|---|---|---|---|
| Bulk statistics | DESeq2 negative-binomial GLM, Wald test, BH adjustment | 1.42.0 | external runtime (R worker) | awaiting SME sign-off |
| Single-cell toolkit | Scanpy over AnnData, `.h5ad` internal object | 1.10.1 | external runtime | awaiting SME sign-off |
| Clustering | Leiden (`leidenalg`), constrained resolution control | 0.10.2 | external runtime | awaiting SME sign-off |
| Embedding | UMAP (`umap-learn`), 2 components, Euclidean over the PCA space, seed fixed at 0; installed version checked against the lock at run time | 0.5.12 | external runtime | awaiting SME sign-off |
| Doublet detection | Scrublet, via `scanpy.pp.scrublet` | 1.10.1 | external runtime | awaiting SME sign-off |
| Pathway enrichment | Hypergeometric over-representation; MSigDB Hallmark v2023.2.Hs, HGNC symbols, background = genes detected in the analysed matrix | GSEApy 1.1.3 | validated in-pipeline + locked collection | awaiting SME sign-off |
| Cell communication | Mean ligand-receptor expression per cell type pair with a cell-label permutation null (the CellPhoneDB statistic); CellPhoneDB v5 curated interactions | communication-1.0.0 | validated in-pipeline + locked database | awaiting SME sign-off |
| Spatial deconvolution | Cell2location cell type abundance per spot | 0.1.4 | external runtime (spatial worker) | awaiting SME sign-off |
| Spatially variable genes | Moran's I spatial autocorrelation with a permutation null | advanced-1.0.0 | validated in-pipeline | awaiting SME sign-off |
| Spatial graph | Hex capture-array ring adjacency; kNN, radius and Delaunay restricted to platforms with no regular grid | advanced-1.0.0 | validated in-pipeline | awaiting SME sign-off |

## Why the "choose and freeze" items were chosen

The spec flags doublet detection, cell communication and pathway enrichment as
decisions to make before implementation. The reasoning is recorded in the config
itself:

- **Scrublet** — simulation-based, ships inside the locked Scanpy version so it
  adds no dependency surface, and is widely benchmarked on droplet data of the
  kind the guided Core dataset contains.
- **Hallmark + hypergeometric** — a small, curated, deliberately non-redundant
  collection keeps Week 4 interpretable. Identifier space and background rule
  are frozen alongside the collection, because an enrichment result is not
  reproducible without them.
- **CellPhoneDB statistic + database** — locked before the Week 5 module was
  built. The statistic is fully specified, so it is computed in the validated
  pipeline; the curated interaction database is the external asset and is
  version-locked with it, exactly as the pathway collection is. Which
  interactions the database contains defines what the module can and cannot
  find, so substituting it is a method change.
- **Cell2location** — spot-level deconvolution whose output is cell type
  *abundance*, which is compositional. Every output carrying it is stamped
  `estimate_kind = "compositional"` and `per_spot_identity = False`.

## Pipeline versions

| Pipeline | Version |
|---|---|
| Foundation (Bulk RNA-seq) | `foundation-1.0.0` |
| Core (single-cell RNA-seq) | `core-1.0.0` |
| Advanced (spatial transcriptomics) | `advanced-1.0.0` |
| Cell-Cell Communication Explorer | `communication-1.0.0` |

The communication module is versioned separately from the guided Core pipeline
even though it reads Core data, so revising one does not silently revise runs
recorded against the other.

## SME sign-off

`sme_signoff` is `False` for every method. The Definition of Done requires a
scientific reviewer to sign off each canonical pipeline and its expected output
before production release. `GET /api/admin/method-lock` lists what is still
outstanding, and the admin console surfaces it as a warning.

## External assets to install

| Asset | Script | Needed by |
|---|---|---|
| MSigDB Hallmark gene sets | `scripts/fetch_gene_sets.py` | pathway enrichment on every track |
| CellPhoneDB ligand-receptor pairs | `scripts/fetch_interactions.py` | the communication module |
| Guided teaching datasets | `scripts/fetch_guided_data.py` | the guided Foundation, Core and Advanced workflows |

Both fetch scripts refuse a file that does not match the locked release, because
installing a different collection would make the version recorded on a run
untrue.
