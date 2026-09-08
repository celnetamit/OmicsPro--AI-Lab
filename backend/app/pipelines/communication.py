"""Cell-Cell Communication Explorer (spec 5.2) — an extension of the Core track.

The framework is locked before the module was built and cannot be swapped at
runtime: the statistic is the mean ligand-receptor expression of a cell type
pair against a cell-label permutation null, and the curated interaction database
is a version-locked external asset.

Everything this module reports is *inferred candidate* communication. Two cell
types co-expressing a ligand and its receptor is consistent with signalling and
is not evidence that any cell touched, secreted, or responded to anything. That
wording is attached to the outputs themselves, not left to the interface.

The run repeats the Core preparation steps rather than reading another run's
state, so a communication run is reconstructable on its own (spec 14.6).
"""

from typing import Dict, List, Tuple

import numpy as np

from app.constants import MODULE_PIPELINE_VERSIONS, AnalysisTrack
from app.pipelines import core, locked, reference as ref
from app.pipelines.base import Pipeline, Step, StepContext, StepFailure

N_PERMUTATIONS = 100

#: Fixed vocabulary for what an interaction result is allowed to be called.
EVIDENCE_KIND = "inferred_candidate_communication"


def _cell_type_labels(ctx: StepContext) -> np.ndarray:
    return np.asarray(core._cell_type_labels(ctx))


def _expression_screen(ctx: StepContext) -> Dict[str, object]:
    """Which ligands and receptors are present in which annotated cell type."""
    pairs = locked.load_ligand_receptor_pairs()
    genes = list(ctx.data.var)
    index = {gene: i for i, gene in enumerate(genes)}

    usable: List[Tuple[str, str]] = []
    missing: List[str] = []
    for pair in pairs:
        ligand, receptor = str(pair["ligand"]), str(pair["receptor"])
        if ligand in index and receptor in index:
            usable.append((ligand, receptor))
        else:
            missing.append(f"{ligand}-{receptor}")
    if not usable:
        raise StepFailure(
            "None of the curated ligand-receptor pairs are measurable in this "
            "dataset. With no testable pair there is nothing to infer.",
            f"{len(pairs)} pairs in the database, none with both genes present",
        )

    labels = _cell_type_labels(ctx)
    normalised = ctx.data.layers["normalised"]
    min_cells = ctx.parameters["comm.min_cells_per_type"]
    min_pct = ctx.parameters["comm.min_expression_pct"]

    cell_types, dropped = [], []
    for cell_type in sorted(set(labels.tolist())):
        n_cells = int((labels == cell_type).sum())
        if n_cells < min_cells:
            dropped.append({"cellType": cell_type, "nCells": n_cells})
        else:
            cell_types.append(cell_type)
    if len(cell_types) < 2:
        raise StepFailure(
            "Fewer than two cell types have enough cells to summarise ligand and "
            "receptor expression reliably. Lower the minimum cells per cell type "
            "or use coarser annotations."
        )

    gene_names = sorted({gene for pair in usable for gene in pair})
    columns = [index[gene] for gene in gene_names]
    means = np.zeros((len(cell_types), len(gene_names)))
    percents = np.zeros_like(means)
    for i, cell_type in enumerate(cell_types):
        mask = labels == cell_type
        block = normalised[mask][:, columns]
        means[i] = block.mean(axis=0)
        percents[i] = (block > 0).mean(axis=0) * 100

    ctx.data.meta["comm"] = {
        "pairs": usable,
        "cell_types": cell_types,
        "gene_names": gene_names,
        "columns": columns,
        "means": means,
        "percents": percents,
        "labels": labels,
    }

    return {
        "n_pairs_in_database": len(pairs),
        "n_pairs_measurable": len(usable),
        "n_pairs_unmeasurable": len(missing),
        "cell_types": cell_types,
        "dropped_cell_types": dropped,
        "min_percent_expressing": min_pct,
        "caveat": (
            "A gene counts as present when enough cells of the type detect it. "
            "Single-cell detection is sparse, so absence here means not detected, "
            "not not expressed."
        ),
    }


def _candidate_pairs(ctx: StepContext) -> Dict[str, object]:
    """Score every ordered cell type pair against a cell-label permutation null."""
    state = ctx.data.meta["comm"]
    cell_types = state["cell_types"]
    gene_names = state["gene_names"]
    gene_index = {gene: i for i, gene in enumerate(gene_names)}
    means, percents = state["means"], state["percents"]
    min_pct = ctx.parameters["comm.min_expression_pct"]

    ligand_idx = np.array([gene_index[ligand] for ligand, _ in state["pairs"]])
    receptor_idx = np.array([gene_index[receptor] for _, receptor in state["pairs"]])

    def score(matrix: np.ndarray) -> np.ndarray:
        """Scores as pair × source type × target type."""
        return (
            matrix[:, ligand_idx].T[:, :, None] + matrix[:, receptor_idx].T[:, None, :]
        ) / 2.0

    observed = score(means)
    # A pair is only a candidate when both partners clear the detection floor in
    # their own cell type; otherwise its score is not tested at all.
    expressed = (
        (percents[:, ligand_idx].T[:, :, None] >= min_pct)
        & (percents[:, receptor_idx].T[:, None, :] >= min_pct)
    )

    normalised = ctx.data.layers["normalised"][:, state["columns"]]
    labels = state["labels"]
    rng = np.random.default_rng(0)
    exceed = np.zeros_like(observed)
    for _ in range(N_PERMUTATIONS):
        shuffled = labels[rng.permutation(labels.size)]
        permuted_means = np.array(
            [normalised[shuffled == cell_type].mean(axis=0) for cell_type in cell_types]
        )
        exceed += score(permuted_means) >= observed
    pvalues = (exceed + 1) / (N_PERMUTATIONS + 1)

    flat_p, coordinates = [], []
    for p_index in range(observed.shape[0]):
        for source in range(len(cell_types)):
            for target in range(len(cell_types)):
                if not expressed[p_index, source, target]:
                    continue
                flat_p.append(pvalues[p_index, source, target])
                coordinates.append((p_index, source, target))
    if not flat_p:
        return {
            "n_tested": 0,
            "n_significant": 0,
            "table": [],
            "evidenceKind": EVIDENCE_KIND,
            "note": (
                "No ligand-receptor pair had both partners above the detection "
                "floor in any cell type, so nothing was tested."
            ),
        }

    padj = ref.benjamini_hochberg(flat_p)
    threshold = ctx.parameters["comm.interaction_fdr"]
    rows = []
    for (p_index, source, target), pvalue, adjusted in zip(coordinates, flat_p, padj):
        ligand, receptor = state["pairs"][p_index]
        rows.append(
            {
                "ligand": ligand,
                "receptor": receptor,
                "source": cell_types[source],
                "target": cell_types[target],
                "score": float(observed[p_index, source, target]),
                "pvalue": float(pvalue),
                "padj": float(adjusted),
                "significant": bool(adjusted < threshold),
            }
        )
    rows.sort(key=lambda r: r["padj"])
    significant = [row for row in rows if row["significant"]]
    ctx.data.meta["comm"]["significant"] = significant

    return {
        "n_tested": len(rows),
        "n_significant": len(significant),
        "top_interactions": [
            f"{row['ligand']}-{row['receptor']}: {row['source']} to {row['target']}"
            for row in significant[:5]
        ],
        "table": rows[:500],
        "evidenceKind": EVIDENCE_KIND,
        "caveat": (
            "Every row is an inferred candidate interaction based on co-expression "
            "of a ligand and its receptor in two cell populations. It is not "
            "demonstrated physical signalling, and the permutation test says only "
            "that the co-expression is unlikely under a random assignment of "
            "cells to types."
        ),
    }


def _condition_comparison(ctx: StepContext) -> Dict[str, object]:
    """Compare candidate interactions between conditions, sample-aware.

    The unit of replication is the sample here for the same reason it is in the
    differential expression step: cells within a donor are not independent.
    """
    obs = ctx.data.obs
    conditions = sorted({row["condition"] for row in obs})
    samples_per_condition = {
        condition: len({row["sample_id"] for row in obs if row["condition"] == condition})
        for condition in conditions
    }
    significant = ctx.data.meta["comm"].get("significant", [])

    if len(conditions) < 2:
        return {
            "performed": False,
            "reason": "The dataset holds one condition, so there is nothing to compare.",
            "evidenceKind": EVIDENCE_KIND,
        }
    underpowered = [c for c, n in samples_per_condition.items() if n < 2]

    state = ctx.data.meta["comm"]
    labels = state["labels"]
    normalised = ctx.data.layers["normalised"][:, state["columns"]]
    gene_index = {gene: i for i, gene in enumerate(state["gene_names"])}
    condition_of = np.asarray([row["condition"] for row in obs])

    rows = []
    for interaction in significant[:100]:
        values = {}
        for condition in conditions:
            source = (labels == interaction["source"]) & (condition_of == condition)
            target = (labels == interaction["target"]) & (condition_of == condition)
            if source.sum() < 3 or target.sum() < 3:
                values[condition] = None
                continue
            ligand = normalised[source, gene_index[interaction["ligand"]]].mean()
            receptor = normalised[target, gene_index[interaction["receptor"]]].mean()
            values[condition] = float((ligand + receptor) / 2)
        first, second = conditions[0], conditions[1]
        if values[first] is None or values[second] is None:
            continue
        rows.append(
            {
                "ligand": interaction["ligand"],
                "receptor": interaction["receptor"],
                "source": interaction["source"],
                "target": interaction["target"],
                "scoreByCondition": values,
                "difference": round(values[second] - values[first], 4),
                "contrast": f"{second} vs {first}",
            }
        )
    rows.sort(key=lambda r: abs(r["difference"]), reverse=True)

    return {
        "performed": True,
        "conditions": conditions,
        "samplesPerCondition": samples_per_condition,
        "underpoweredConditions": underpowered,
        "n_compared": len(rows),
        "table": rows[:200],
        "evidenceKind": EVIDENCE_KIND,
        "replicate_unit": "sample",
        "caveat": (
            "Differences in interaction score are descriptive. With "
            f"{min(samples_per_condition.values())} sample(s) in the smallest "
            "condition group, treat any between-condition difference as a "
            "hypothesis rather than a tested effect."
        ),
    }


def _mechanism(ctx: StepContext) -> Dict[str, object]:
    """Assemble the candidate mechanism the learner will write up."""
    significant = ctx.data.meta["comm"].get("significant", [])
    if not significant:
        return {
            "n_candidates": 0,
            "candidates": [],
            "evidenceKind": EVIDENCE_KIND,
            "note": (
                "No candidate interaction passed the significance threshold, so "
                "no mechanism is proposed. That is a result, not a failure."
            ),
        }
    candidates = []
    for interaction in significant[:10]:
        candidates.append(
            {
                "ligand": interaction["ligand"],
                "receptor": interaction["receptor"],
                "source": interaction["source"],
                "target": interaction["target"],
                "padj": interaction["padj"],
                "statement": (
                    f"{interaction['source']} cells express the ligand and "
                    f"{interaction['target']} cells express its receptor above "
                    f"the detection floor, which is consistent with signalling "
                    f"from the first population to the second."
                ),
                "wouldConfirmIt": (
                    "Direct evidence would need a perturbation: block or remove "
                    "the receptor and show the downstream response in the target "
                    "population changes. Co-expression cannot establish that."
                ),
            }
        )
    return {
        "n_candidates": len(candidates),
        "candidates": candidates,
        "evidenceKind": EVIDENCE_KIND,
        "caveat": (
            "These are candidate mechanisms to test, not findings. Nothing in "
            "this module observes signalling."
        ),
    }


PIPELINE = Pipeline(
    track=AnalysisTrack.CORE,
    version=MODULE_PIPELINE_VERSIONS["core_communication"],
    steps=[
        # Preparation repeats the Core steps so this run stands alone.
        core.PIPELINE.step("validate"),
        core.PIPELINE.step("cell_qc"),
        core.PIPELINE.step("feature_selection"),
        core.PIPELINE.step("dimensionality_reduction"),
        core.PIPELINE.step("clustering"),
        core.PIPELINE.step("marker_genes"),
        Step(
            "communication",
            "Ligand and receptor screen",
            ["comm.min_cells_per_type", "comm.min_expression_pct"],
            "expression",
            _expression_screen,
            requires_method="cell_communication",
        ),
        Step(
            "candidate_pairs",
            "Candidate interactions",
            ["comm.interaction_fdr", "comm.min_expression_pct"],
            "interactions",
            _candidate_pairs,
            requires_method="cell_communication",
        ),
        Step(
            "condition_comparison",
            "Comparison between conditions",
            [],
            "comm_condition",
            _condition_comparison,
        ),
        Step(
            "candidate_mechanism",
            "Candidate mechanism",
            [],
            "mechanism",
            _mechanism,
        ),
    ],
)
