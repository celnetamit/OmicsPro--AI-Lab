"""Readers that turn an analysis-ready file into the internal object layout.

Both routes into the platform read through here: the Expert upload and the
operator's ingestion of the guided datasets. A format therefore means the same
thing on both, and the stored object always has the orientation the pipelines
read:

    Foundation   genes × samples
    Core         cells × genes
    Advanced     spots × genes

Metadata is matched to the matrix by identifier rather than assumed to be in
the same order: a silent misalignment would attach the wrong condition to every
observation, and nothing downstream could detect it. Only raw counts are
accepted, because the locked methods model counts; normalised values cannot
stand in for them.
"""

import contextlib
import gzip
import io
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import io as scipy_io
from scipy import sparse

from app.constants import AnalysisTrack

#: The observation identifier each track's pipeline reads.
CANONICAL_ID = {
    AnalysisTrack.FOUNDATION: "sample_id",
    AnalysisTrack.CORE: "cell_id",
    AnalysisTrack.ADVANCED: "spot_id",
}
#: Metadata columns that may name an observation, tried in this order.
ID_CANDIDATES = {
    AnalysisTrack.FOUNDATION: ("sample_id", "sample"),
    AnalysisTrack.CORE: ("cell_id", "barcode", "cell"),
    AnalysisTrack.ADVANCED: ("spot_id", "barcode"),
}
UNIT = {
    AnalysisTrack.FOUNDATION: "sample",
    AnalysisTrack.CORE: "cell",
    AnalysisTrack.ADVANCED: "spot",
}

#: The analysis object is dense in memory. Past this many values an ingestion
#: is refused unless the operator takes a recorded, seeded subsample.
DEFAULT_MAX_VALUES = 250_000_000

#: Symbol columns preferred over identifiers when a file carries both: the
#: pipelines read symbols (mitochondrial genes are found by their MT- prefix).
SYMBOL_COLUMNS = (
    "gene_symbols", "gene_symbol", "feature_name", "gene_name", "gene_names", "symbol",
)

#: Visium tissue_positions columns, in Space Ranger's order.
POSITION_COLUMNS = [
    "barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres",
]

TABLE_EXTENSIONS = (".csv", ".tsv", ".txt")


class IngestError(ValueError):
    """The file cannot become an analysis object. The message says why and what to do."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def logical_extension(filename: str) -> str:
    """The format a file holds: 'matrix.mtx.gz' is '.mtx', 'reads.fastq.gz' is '.fastq'."""
    name = filename.lower()
    if name.endswith(".gz"):
        return os.path.splitext(name[:-3])[1] or ".gz"
    return os.path.splitext(name)[1]


@dataclass
class Source:
    """One input file, read from disk (operator) or from an upload (in memory)."""

    name: str
    path: Optional[str] = None
    data: Optional[bytes] = None

    @classmethod
    def from_path(cls, path: str) -> "Source":
        return cls(os.path.basename(path), path=path)

    @property
    def size(self) -> int:
        return len(self.data) if self.data is not None else os.path.getsize(self.path)

    @property
    def extension(self) -> str:
        return logical_extension(self.name)

    def open(self):
        raw = io.BytesIO(self.data) if self.data is not None else open(self.path, "rb")
        return gzip.GzipFile(fileobj=raw) if self.name.lower().endswith(".gz") else raw


@dataclass
class Ingested:
    """A validated-shape analysis object, ready to be stored."""

    matrix: np.ndarray
    obs: List[dict]
    var: List[str]
    #: What was done to the data on the way in, recorded with the dataset.
    notes: List[str] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)

    def write(self, base: str) -> None:
        os.makedirs(os.path.dirname(base), exist_ok=True)
        np.savez_compressed(f"{base}.npz", matrix=self.matrix)
        with open(f"{base}.meta.json", "w") as handle:
            json.dump({"obs": self.obs, "var": self.var}, handle)


@dataclass
class _Raw:
    """Counts as features × observations, before metadata is attached."""

    counts: object  # ndarray or scipy sparse matrix
    genes: List[str]
    observations: Optional[List[str]]
    embedded: Optional[List[dict]] = None
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers --
def _plain(value):
    return value.item() if isinstance(value, np.generic) else value


def _missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _frame_rows(frame: pd.DataFrame) -> List[dict]:
    return [
        {str(key): _plain(value) for key, value in record.items() if not _missing(value)}
        for record in frame.to_dict("records")
    ]


def _lines(source: Source) -> List[str]:
    with source.open() as handle:
        return [line.decode().rstrip("\r\n") for line in handle if line.strip()]


def _unique(names: List[str]) -> Tuple[List[str], int]:
    seen: Dict[str, int] = {}
    out = []
    for name in names:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}-{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out, sum(seen.values())


def _symbols(var: pd.DataFrame) -> List[str]:
    for column in SYMBOL_COLUMNS:
        if column in var.columns:
            return [str(v) for v in var[column]]
    return [str(v) for v in var.index]


def _integral(matrix) -> bool:
    values = matrix.data if sparse.issparse(matrix) else np.asarray(matrix)
    if values.size == 0:
        return False
    return bool(
        np.isfinite(values).all() and (values >= 0).all() and np.equal(np.mod(values, 1), 0).all()
    )


@contextlib.contextmanager
def _local_path(source: Source, suffix: str) -> Iterator[str]:
    """A filesystem path for libraries that will not read from memory."""
    if source.path is not None:
        yield source.path
        return
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        handle.write(source.data)
        handle.close()
        yield handle.name
    finally:
        os.remove(handle.name)


# ---------------------------------------------------------------- readers --
def read_metadata(source: Optional[Source]) -> List[dict]:
    if source is None:
        return []
    sep = "\t" if source.extension in (".tsv", ".txt") else ","
    try:
        with source.open() as handle:
            frame = pd.read_csv(handle, sep=sep)
    except Exception as exc:
        raise IngestError(
            "unreadable_file",
            "The metadata could not be read as a table with a header row.",
        ) from exc
    return _frame_rows(frame)


def _read_table(source: Source, id_values: Optional[set]) -> _Raw:
    sep = "\t" if source.extension in (".tsv", ".txt") else ","
    try:
        with source.open() as handle:
            frame = pd.read_csv(handle, index_col=0, sep=sep)
    except Exception as exc:
        raise IngestError(
            "unreadable_file",
            "The uploaded files could not be read as a table. Upload an analysis-ready "
            "matrix with genes as rows and samples or cells as columns, plus a metadata table.",
        ) from exc
    columns = [str(c) for c in frame.columns]
    index = [str(i) for i in frame.index]
    #: Whichever axis carries the metadata's identifiers is the observation axis.
    if id_values and not id_values.intersection(columns) and id_values.intersection(index):
        frame = frame.T
        columns, index = index, columns
    try:
        counts = frame.to_numpy(dtype=float)
    except ValueError as exc:
        raise IngestError(
            "non_numeric_matrix", "The matrix holds values that are not numbers."
        ) from exc
    return _Raw(counts=counts, genes=index, observations=columns)


def _features(source: Source) -> Tuple[List[str], Optional[np.ndarray]]:
    rows = [line.split("\t") for line in _lines(source)]
    names = [row[1] if len(row) > 1 and row[1] else row[0] for row in rows]
    keep = None
    if rows and all(len(row) > 2 for row in rows):
        expression = np.array([row[2] == "Gene Expression" for row in rows])
        if expression.any() and not expression.all():
            keep = np.flatnonzero(expression)
    return names, keep


def _read_mtx(matrix: Source, features: Optional[Source], barcodes: Optional[Source]) -> _Raw:
    try:
        with matrix.open() as handle:
            counts = sparse.csr_matrix(scipy_io.mmread(handle))
    except Exception as exc:
        raise IngestError(
            "unreadable_file", "The .mtx file could not be read as a Matrix Market matrix."
        ) from exc
    if features is None:
        raise IngestError(
            "missing_features",
            "A .mtx matrix carries no gene names. Supply the features.tsv (or genes.tsv) "
            "file that came with it.",
        )
    genes, keep = _features(features)
    notes = []
    rows, cols = counts.shape
    if len(genes) == cols and len(genes) != rows:
        counts = counts.T.tocsr()
        rows, cols = cols, rows
    if len(genes) != rows:
        raise IngestError(
            "matrix_feature_mismatch",
            f"The matrix is {rows} × {cols} but the features file lists {len(genes)} genes.",
        )
    if keep is not None:
        counts = counts[keep]
        genes = [genes[i] for i in keep]
        notes.append(
            f"Kept the {len(keep)} Gene Expression features; other feature types (for "
            f"example antibody capture) are not part of this analysis."
        )
    cells = _lines(barcodes) if barcodes is not None else None
    if cells is not None and len(cells) != counts.shape[1]:
        raise IngestError(
            "matrix_barcode_mismatch",
            f"The matrix has {counts.shape[1]} columns but the barcodes file lists {len(cells)}.",
        )
    return _Raw(counts=counts, genes=genes, observations=cells, notes=notes)


def _read_10x_h5(source: Source) -> _Raw:
    try:
        import h5py
    except ImportError:
        raise IngestError(
            "format_not_readable",
            "Reading 10x HDF5 files needs h5py, which this deployment does not include. "
            "Build the API image with INCLUDE_SCIENCE=true.",
        )
    try:
        with h5py.File(io.BytesIO(source.data) if source.data is not None else source.path, "r") as f:
            if "matrix" in f:  # Cell Ranger 3 and later
                group = f["matrix"]
                names = [n.decode() for n in group["features"]["name"][:]]
                types = [t.decode() for t in group["features"]["feature_type"][:]]
            else:  # Cell Ranger 2: one group per genome
                group = f[list(f.keys())[0]]
                names = [n.decode() for n in group["gene_names"][:]]
                types = None
            counts = sparse.csc_matrix(
                (group["data"][:], group["indices"][:], group["indptr"][:]),
                shape=tuple(int(v) for v in group["shape"][:]),
            )
            barcodes = [b.decode() for b in group["barcodes"][:]]
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(
            "unreadable_file", "The .h5 file could not be read as a 10x feature-barcode matrix."
        ) from exc
    notes = []
    if types is not None:
        keep = np.flatnonzero([t == "Gene Expression" for t in types])
        if 0 < len(keep) < len(types):
            counts = counts[keep]
            names = [names[i] for i in keep]
            notes.append(
                f"Kept the {len(keep)} Gene Expression features; other feature types are "
                f"not part of this analysis."
            )
    return _Raw(counts=counts.tocsr(), genes=names, observations=barcodes, notes=notes)


def _read_h5ad(source: Source) -> _Raw:
    try:
        import anndata
    except ImportError:
        raise IngestError(
            "format_not_readable",
            "Reading .h5ad files needs anndata, which this deployment does not include. "
            "Build the API image with INCLUDE_SCIENCE=true.",
        )
    with _local_path(source, ".h5ad") as path:
        try:
            adata = anndata.read_h5ad(path)
        except Exception as exc:
            raise IngestError(
                "unreadable_file", "The .h5ad file could not be read as an AnnData object."
            ) from exc

    candidates = []
    if "counts" in adata.layers:
        candidates.append(("the 'counts' layer", adata.layers["counts"], adata.var))
    if adata.raw is not None:
        candidates.append(("the raw matrix (.raw)", adata.raw.X, adata.raw.var))
    candidates.append(("the main matrix (.X)", adata.X, adata.var))
    chosen = next((c for c in candidates if _integral(c[1])), None)
    if chosen is None:
        raise IngestError(
            "not_raw_counts",
            "No matrix in this .h5ad holds raw counts (non-negative whole numbers). The "
            "locked methods model counts, so normalised or scaled values cannot stand in. "
            "Include the counts as a 'counts' layer or as .raw.",
        )
    label, matrix, var = chosen
    embedded = _frame_rows(adata.obs)
    if "spatial" in adata.obsm:
        coordinates = np.asarray(adata.obsm["spatial"])
        for row, (x, y) in zip(embedded, coordinates[:, :2]):
            row.setdefault("x", float(x))
            row.setdefault("y", float(y))
    counts = sparse.csr_matrix(matrix).T.tocsr() if sparse.issparse(matrix) else np.asarray(matrix).T
    return _Raw(
        counts=counts,
        genes=_symbols(var),
        observations=[str(name) for name in adata.obs_names],
        embedded=embedded,
        notes=[f"Counts read from {label}."],
    )


def read_positions(source: Source) -> Dict[str, dict]:
    """Visium tissue positions, with or without Space Ranger's header row."""
    try:
        with source.open() as handle:
            frame = pd.read_csv(handle, header=None, dtype=str)
    except Exception as exc:
        raise IngestError(
            "unreadable_positions", "The tissue positions file could not be read as a table."
        ) from exc
    if str(frame.iloc[0, 1]).strip().lower() == "in_tissue":
        frame = frame.iloc[1:]
    if frame.shape[1] < len(POSITION_COLUMNS):
        raise IngestError(
            "unreadable_positions",
            "Tissue positions need six columns: barcode, in_tissue, array_row, array_col "
            "and the full-resolution pixel row and column.",
        )
    frame = frame.iloc[:, : len(POSITION_COLUMNS)]
    frame.columns = POSITION_COLUMNS
    return {
        str(row.barcode): {
            "in_tissue": int(row.in_tissue),
            "array_row": int(row.array_row),
            "array_col": int(row.array_col),
            #: Image convention: x runs along pixel columns, y down pixel rows.
            "x": float(row.pxl_col_in_fullres),
            "y": float(row.pxl_row_in_fullres),
        }
        for row in frame.itertuples(index=False)
    }


# -------------------------------------------------------------- assembly --
def _metadata_ids(track: AnalysisTrack, rows: List[dict]) -> Tuple[Optional[str], Optional[set]]:
    for candidate in ID_CANDIDATES[track]:
        if rows and all(candidate in row for row in rows):
            return candidate, {str(row[candidate]) for row in rows}
    return None, None


def ingest(
    track: AnalysisTrack,
    matrix: Source,
    metadata: Optional[Source] = None,
    *,
    features: Optional[Source] = None,
    barcodes: Optional[Source] = None,
    positions: Optional[Source] = None,
    defaults: Optional[Dict[str, str]] = None,
    max_observations: Optional[int] = None,
    seed: int = 0,
    min_cells_per_gene: int = 0,
    max_values: int = DEFAULT_MAX_VALUES,
) -> Ingested:
    """Read ``matrix`` (and its companions) into the stored layout for ``track``."""
    rows = read_metadata(metadata)
    id_field, id_values = _metadata_ids(track, rows)
    extension = matrix.extension
    if extension in TABLE_EXTENSIONS:
        raw = _read_table(matrix, id_values)
    elif extension == ".mtx":
        raw = _read_mtx(matrix, features, barcodes)
    elif extension == ".h5":
        raw = _read_10x_h5(matrix)
    elif extension == ".h5ad":
        raw = _read_h5ad(matrix)
    elif extension in (".rds", ".rdata"):
        raise IngestError(
            "format_not_readable",
            "R objects need the R worker image to be read, and this deployment does not "
            "run it. Export the object to .h5ad and upload that instead.",
        )
    elif extension == ".npz":
        raise IngestError(
            "format_not_readable",
            "An .npz holds arrays but not the gene and sample names that belong to them, "
            "so it cannot be read on its own. Upload a CSV/TSV, 10x or .h5ad file instead.",
        )
    else:
        raise IngestError(
            "format_not_readable", f"'{extension}' files cannot be read into an analysis object."
        )
    return _assemble(
        track, raw, rows, id_field, positions, defaults or {},
        max_observations, seed, min_cells_per_gene, max_values,
    )


def _assemble(
    track, raw: _Raw, rows, id_field, positions, defaults,
    max_observations, seed, min_cells_per_gene, max_values,
) -> Ingested:
    unit = UNIT[track]
    notes = list(raw.notes)
    warnings: List[dict] = []
    counts = raw.counts
    genes = list(raw.genes)
    observations = raw.observations
    n_obs = counts.shape[1]

    obs_rows = [dict(r) for r in raw.embedded] if raw.embedded is not None else [{} for _ in range(n_obs)]
    if rows:
        if id_field and observations is not None:
            by_id: Dict[str, dict] = {}
            for row in rows:
                by_id.setdefault(str(row[id_field]), row)
            missing = [o for o in observations if o not in by_id]
            if missing:
                raise IngestError(
                    "metadata_mismatch",
                    f"{len(missing)} of the {n_obs} {unit}s in the matrix have no metadata row "
                    f"(for example '{missing[0]}'). Every {unit} needs one, matched on {id_field}.",
                )
            for row, name in zip(obs_rows, observations):
                row.update(by_id[name])
            unused = len(by_id) - n_obs
            if unused > 0:
                warnings.append({
                    "code": "metadata_rows_unused",
                    "message": f"{unused} metadata rows name {unit}s that are not in the matrix and were not used.",
                })
        elif len(rows) == n_obs:
            for row, supplied in zip(obs_rows, rows):
                row.update(supplied)
            warnings.append({
                "code": "metadata_matched_by_position",
                "message": (
                    f"The metadata has no column naming each {unit} as the matrix does, so rows "
                    f"were matched by position. Check that both are in the same order."
                ),
            })
        else:
            raise IngestError(
                "matrix_metadata_mismatch",
                f"The matrix describes {n_obs} {unit}s but the metadata has {len(rows)} rows, "
                f"and no column identifies which row belongs to which {unit}.",
            )

    canonical = CANONICAL_ID[track]
    for i, row in enumerate(obs_rows):
        if canonical not in row:
            row[canonical] = observations[i] if observations is not None else f"{unit}{i + 1}"

    if positions is not None:
        if observations is None:
            raise IngestError(
                "missing_barcodes",
                "Tissue positions are matched by barcode, so the matrix needs its barcodes.",
            )
        placed = read_positions(positions)
        unplaced = [o for o in observations if o not in placed]
        if unplaced:
            raise IngestError(
                "positions_mismatch",
                f"{len(unplaced)} spots in the matrix have no tissue position (for example "
                f"'{unplaced[0]}').",
            )
        keep = [i for i, o in enumerate(observations) if placed[o]["in_tissue"] == 1]
        if len(keep) < n_obs:
            notes.append(
                f"Kept the {len(keep)} spots under tissue; {n_obs - len(keep)} spots outside "
                f"it were dropped."
            )
        counts = counts[:, keep]
        obs_rows = [obs_rows[i] for i in keep]
        observations = [observations[i] for i in keep]
        for row, name in zip(obs_rows, observations):
            position = placed[name]
            row.update({k: position[k] for k in ("x", "y", "array_row", "array_col")})
        n_obs = len(keep)

    for key, value in defaults.items():
        for row in obs_rows:
            row.setdefault(key, value)
        notes.append(f"Every {unit} without one was given {key} = {value} at ingestion.")

    if not _integral(counts):
        raise IngestError(
            "not_raw_counts",
            "The matrix does not hold raw counts (non-negative whole numbers). The locked "
            "methods model counts, so normalised, scaled or log-transformed values cannot "
            "stand in; supply the raw count matrix.",
        )

    n_genes = counts.shape[0]
    if min_cells_per_gene > 0:
        detected = np.asarray((counts > 0).sum(axis=1)).ravel()
        kept = np.flatnonzero(detected >= min_cells_per_gene)
        counts = counts[kept]
        genes = [genes[i] for i in kept]
        notes.append(
            f"Kept the {len(kept)} of {n_genes} genes detected in at least "
            f"{min_cells_per_gene} {unit}s."
        )

    if max_observations and n_obs > max_observations:
        chosen = np.sort(np.random.default_rng(seed).choice(n_obs, size=max_observations, replace=False))
        counts = counts[:, chosen]
        obs_rows = [obs_rows[i] for i in chosen]
        notes.append(
            f"Ingested as a seeded subsample of {max_observations} of {n_obs} {unit}s "
            f"(seed {seed}); results describe the subsample."
        )

    n_values = counts.shape[0] * counts.shape[1]
    if n_values > max_values:
        raise IngestError(
            "too_large_for_dense_object",
            f"{counts.shape[1]} {unit}s × {counts.shape[0]} genes is {n_values:,} values, above "
            f"the {max_values:,} the analysis object holds in memory. Take a recorded, seeded "
            f"subsample or drop rarely detected genes before ingesting.",
        )

    dense = counts.toarray() if sparse.issparse(counts) else np.asarray(counts)
    dense = dense.astype(np.int32 if dense.max(initial=0) < 2 ** 31 else np.int64)
    genes, renamed = _unique(genes)
    if renamed:
        warnings.append({
            "code": "duplicate_gene_names",
            "message": f"{renamed} gene names occurred more than once and were suffixed to keep them apart.",
        })
    matrix = dense if track is AnalysisTrack.FOUNDATION else dense.T
    return Ingested(
        matrix=np.ascontiguousarray(matrix), obs=obs_rows, var=genes, notes=notes, warnings=warnings
    )
