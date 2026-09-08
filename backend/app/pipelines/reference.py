"""Reference compute backend: the steps that are not bound to a locked method.

Everything here is ordinary, inspectable numerics on the validated data object —
library sizes, filtering, PCA, pseudobulk aggregation, Benjamini-Hochberg
correction, hypergeometric over-representation. Steps that *are* bound to a
locked method (DESeq2, Leiden, Scrublet) live in ``locked.py`` and are never
approximated here, because a substituted method would make the version stamped
on the run untrue.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import sparse, stats


def library_sizes(matrix: np.ndarray) -> np.ndarray:
    """Total counts per sample (columns of a genes-by-samples matrix)."""
    return np.asarray(matrix).sum(axis=0)


def detected_genes(matrix: np.ndarray, min_count: int = 1) -> np.ndarray:
    return (np.asarray(matrix) >= min_count).sum(axis=0)


def filter_low_information(
    matrix: np.ndarray, min_counts: int, min_samples: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Keep genes with >= ``min_counts`` in >= ``min_samples`` samples.

    Applied independently of the condition labels so it does not bias p-values.
    """
    matrix = np.asarray(matrix)
    keep = (matrix >= min_counts).sum(axis=1) >= min_samples
    return matrix[keep], keep


def cpm_log(matrix: np.ndarray) -> np.ndarray:
    """Log counts-per-million, used for exploratory structure only."""
    matrix = np.asarray(matrix, dtype=float)
    sizes = matrix.sum(axis=0)
    sizes[sizes == 0] = 1.0
    return np.log1p(matrix / sizes * 1e6)


def pca(values: np.ndarray, n_components: int) -> Dict[str, object]:
    """Principal components of a features-by-observations matrix."""
    values = np.asarray(values, dtype=float)
    centered = values - values.mean(axis=1, keepdims=True)
    n_components = int(min(n_components, min(centered.shape) - 1))
    if n_components < 1:
        raise ValueError("Not enough observations to compute principal components.")
    _, singular, vt = np.linalg.svd(centered, full_matrices=False)
    variance = singular**2
    ratio = variance / variance.sum() if variance.sum() else np.zeros_like(variance)
    return {
        "coordinates": (vt[:n_components] * singular[:n_components, None]).T,
        "variance_ratio": ratio[:n_components],
    }


def dominant_grouping(coordinates: np.ndarray, candidate_labels: Dict[str, Sequence]) -> str:
    """Which annotation best explains separation on the first component.

    Reported so a learner sees when structure is driven by batch or donor rather
    than by the condition of interest.
    """
    pc1 = np.asarray(coordinates)[:, 0]
    best_field, best_stat = "none", 0.0
    for field, labels in candidate_labels.items():
        groups = [pc1[np.asarray(labels) == level] for level in sorted(set(labels))]
        groups = [g for g in groups if len(g) > 0]
        if len(groups) < 2 or any(len(g) < 2 for g in groups):
            continue
        stat = float(stats.f_oneway(*groups).statistic)
        if np.isfinite(stat) and stat > best_stat:
            best_field, best_stat = field, stat
    return best_field


def benjamini_hochberg(pvalues: Sequence[float]) -> np.ndarray:
    """Standard BH step-up adjustment."""
    p = np.asarray(pvalues, dtype=float)
    n = p.size
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(n)
    adjusted[order] = np.clip(ranked, 0, 1)
    return adjusted


def pseudobulk(
    matrix: np.ndarray, sample_labels: Sequence, cell_type_labels: Sequence, min_cells: int
) -> Dict[str, object]:
    """Sum counts per (sample, cell type) so the replicate unit is the sample.

    Spec 4.2: cells are never treated as independent biological replicates.
    Profiles below ``min_cells`` are dropped and counted, not silently included.
    """
    matrix = np.asarray(matrix)
    samples = np.asarray(sample_labels)
    cell_types = np.asarray(cell_type_labels)

    profiles: List[np.ndarray] = []
    keys: List[Tuple[str, str]] = []
    dropped: List[Tuple[str, str, int]] = []
    for sample in sorted(set(samples.tolist())):
        for cell_type in sorted(set(cell_types.tolist())):
            mask = (samples == sample) & (cell_types == cell_type)
            n_cells = int(mask.sum())
            if n_cells < min_cells:
                if n_cells:
                    dropped.append((str(sample), str(cell_type), n_cells))
                continue
            profiles.append(matrix[mask].sum(axis=0))
            keys.append((str(sample), str(cell_type)))
    return {
        "profiles": np.array(profiles) if profiles else np.empty((0, matrix.shape[1])),
        "keys": keys,
        "dropped": dropped,
    }


def hypergeometric_enrichment(
    query_genes: Sequence[str],
    background_genes: Sequence[str],
    gene_sets: Dict[str, Sequence[str]],
    min_set_size: int,
) -> List[dict]:
    """Over-representation against the *detected-gene* background (locked rule)."""
    background = set(background_genes)
    query = set(query_genes) & background
    results = []
    for name, members in gene_sets.items():
        in_background = set(members) & background
        if len(in_background) < min_set_size:
            continue
        overlap = query & in_background
        if not overlap:
            continue
        pvalue = stats.hypergeom.sf(
            len(overlap) - 1, len(background), len(in_background), len(query)
        )
        results.append(
            {
                "set": name,
                "overlap": sorted(overlap),
                "n_overlap": len(overlap),
                "n_set": len(in_background),
                "pvalue": float(pvalue),
            }
        )
    if not results:
        return []
    adjusted = benjamini_hochberg([r["pvalue"] for r in results])
    for row, value in zip(results, adjusted):
        row["padj"] = float(value)
    return sorted(results, key=lambda r: r["padj"])


# ---------------------------------------------------------------------------
# Spatial numerics (Advanced track). Geometry and Moran's I are exactly
# specified statistics, so they are computed here rather than delegated; the
# locked-method table records that honestly.
# ---------------------------------------------------------------------------


def spatial_graph(
    coordinates: np.ndarray,
    geometry: str,
    *,
    n_rings: int = 1,
    n_neighbors: int = 6,
    radius: float = 0.0,
    grid: Optional[Sequence[Sequence[int]]] = None,
) -> "sparse.csr_matrix":
    """Build the spot adjacency graph for the capture platform.

    ``grid`` gives each spot's array row and column when the platform captures
    on a regular array. Ring adjacency is only meaningful with it, so asking for
    the grid geometry without one is an error rather than a silent fallback to a
    distance rule the assay never measured.
    """
    coordinates = np.asarray(coordinates, dtype=float)
    n = coordinates.shape[0]

    if geometry == "grid":
        if grid is None:
            raise ValueError(
                "The capture-grid geometry needs each spot's array position. "
                "This package does not carry one, so a grid neighbourhood cannot "
                "be built for it."
            )
        return _grid_rings(np.asarray(grid, dtype=int), n_rings)

    distances = np.linalg.norm(coordinates[:, None, :] - coordinates[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)

    if geometry == "knn":
        k = int(min(n_neighbors, max(n - 1, 1)))
        neighbours = np.argsort(distances, axis=1)[:, :k]
        rows = np.repeat(np.arange(n), k)
        cols = neighbours.ravel()
    elif geometry == "radius":
        if radius <= 0:
            raise ValueError(
                "A radius neighbourhood needs a positive radius in the "
                "coordinate units of the capture package."
            )
        rows, cols = np.nonzero(distances <= radius)
    elif geometry == "delaunay":
        from scipy.spatial import Delaunay

        simplices = Delaunay(coordinates).simplices
        edges = set()
        for simplex in simplices:
            for i in range(len(simplex)):
                for j in range(i + 1, len(simplex)):
                    edges.add((int(simplex[i]), int(simplex[j])))
        if not edges:
            raise ValueError("The spot coordinates do not support a triangulation.")
        rows, cols = map(np.array, zip(*edges))
    else:
        raise ValueError(f"'{geometry}' is not a supported spatial geometry.")

    graph = sparse.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n, n)
    )
    return _symmetrise(graph)


def _grid_rings(grid: np.ndarray, n_rings: int) -> "sparse.csr_matrix":
    """Ring adjacency on a hexagonal capture array, in array coordinates.

    The array indexes a hex lattice: within a row the next spot is two columns
    away, and the rows above and below are offset by one. Converting to axial
    coordinates gives the true hex distance, so ring ``n`` is the set of spots
    exactly reachable in ``n`` steps — not a Manhattan ball, which would also
    admit the spot two rows directly above, which is not a neighbour.
    """
    n = grid.shape[0]
    rows_axial = grid[:, 0].astype(np.int64)
    q_axial = (grid[:, 1].astype(np.int64) - rows_axial) // 2

    dq = q_axial[:, None] - q_axial[None, :]
    dr = rows_axial[:, None] - rows_axial[None, :]
    distance = (np.abs(dq) + np.abs(dq + dr) + np.abs(dr)) // 2

    within = (distance > 0) & (distance <= n_rings)
    rows, cols = np.nonzero(within)
    graph = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    return _symmetrise(graph)


def _symmetrise(graph: "sparse.csr_matrix") -> "sparse.csr_matrix":
    graph = graph.maximum(graph.T)
    graph.setdiag(0)
    graph.eliminate_zeros()
    return graph.tocsr()


def morans_i(
    values: np.ndarray, graph: "sparse.csr_matrix", n_permutations: int = 100, seed: int = 0
) -> Dict[str, np.ndarray]:
    """Moran's I per gene, with a permutation null over spot positions.

    ``values`` is spots-by-genes. A positive I means nearby spots hold similar
    values; it measures spatial structure, not biological importance.
    """
    values = np.asarray(values, dtype=float)
    n_spots = values.shape[0]
    weight_total = float(graph.sum())
    if weight_total == 0:
        raise ValueError("The spatial graph has no edges, so Moran's I is undefined.")

    centered = values - values.mean(axis=0, keepdims=True)
    denominator = (centered**2).sum(axis=0)
    denominator[denominator == 0] = np.nan

    def _statistic(matrix: np.ndarray) -> np.ndarray:
        return (n_spots / weight_total) * (matrix * (graph @ matrix)).sum(axis=0) / denominator

    observed = _statistic(centered)

    rng = np.random.default_rng(seed)
    exceed = np.zeros(values.shape[1])
    for _ in range(n_permutations):
        order = rng.permutation(n_spots)
        exceed += _statistic(centered[order]) >= observed
    pvalues = (exceed + 1) / (n_permutations + 1)

    return {
        "I": np.nan_to_num(observed, nan=0.0),
        "pvalue": pvalues,
        "padj": benjamini_hochberg(pvalues),
    }


def neighborhood_enrichment(
    labels: Sequence, graph: "sparse.csr_matrix", n_permutations: int = 200, seed: int = 0
) -> List[dict]:
    """Which region pairs sit next to each other more than chance predicts.

    Adjacency is a description of tissue organisation. It is not evidence of
    interaction between the regions.
    """
    labels = np.asarray(labels)
    levels = sorted(set(labels.tolist()))
    index = {level: i for i, level in enumerate(levels)}
    codes = np.array([index[label] for label in labels])
    rows, cols = graph.nonzero()

    def _counts(assignment: np.ndarray) -> np.ndarray:
        table = np.zeros((len(levels), len(levels)))
        np.add.at(table, (assignment[rows], assignment[cols]), 1)
        return (table + table.T) / 2

    observed = _counts(codes)
    rng = np.random.default_rng(seed)
    exceed = np.zeros_like(observed)
    for _ in range(n_permutations):
        exceed += _counts(codes[rng.permutation(codes.size)]) >= observed
    pvalues = (exceed + 1) / (n_permutations + 1)

    results = []
    for i, a in enumerate(levels):
        for j, b in enumerate(levels):
            if j < i:
                continue
            results.append(
                {
                    "regionA": str(a),
                    "regionB": str(b),
                    "adjacencies": float(observed[i, j]),
                    "pvalue": float(pvalues[i, j]),
                }
            )
    adjusted = benjamini_hochberg([row["pvalue"] for row in results])
    for row, value in zip(results, adjusted):
        row["padj"] = float(value)
    return sorted(results, key=lambda r: r["padj"])
