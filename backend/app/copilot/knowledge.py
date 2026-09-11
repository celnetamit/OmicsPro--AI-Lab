"""Curated Copilot knowledge base.

Every entry is authored content reviewed against the approved evidence registry.
Variable content appears only as ``{{computed:...}}`` / ``{{param:...}}`` /
``{{method:...}}`` references, which ``grounding.render`` resolves from the
actual run. Nothing here may contain a literal result, gene symbol or threshold.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from app.constants import AnalysisTrack


@dataclass(frozen=True)
class StepKnowledge:
    step: str
    track: AnalysisTrack
    title: str
    #: What this step is and why it exists.
    purpose: str
    #: Template rendered against the run's computed outputs (spec 8 "Explain").
    explain_template: str
    what_to_observe: str
    evidence_source_ids: List[str] = field(default_factory=list)
    #: Caveats the UI must show alongside this step's results.
    caveats: List[str] = field(default_factory=list)


_STEPS: List[StepKnowledge] = [
    # ---- Foundation ----------------------------------------------------
    StepKnowledge(
        step="validate",
        track=AnalysisTrack.FOUNDATION,
        title="Validate the count matrix and sample metadata",
        purpose=(
            "Confirm that the count matrix and the sample sheet describe the same "
            "experiment before any model is fitted. A mismatch between matrix "
            "columns and metadata rows silently mislabels every downstream result."
        ),
        explain_template=(
            "The matrix contains {{computed:validate.n_genes}} genes across "
            "{{computed:validate.n_samples}} samples, and every sample column "
            "matched a metadata row. Conditions present: "
            "{{computed:validate.conditions}}, with "
            "{{computed:validate.min_replicates}} replicates in the smallest group."
        ),
        what_to_observe=(
            "Check that the smallest condition group still has enough replicates "
            "to estimate variance. Two samples per group is the practical floor "
            "for a count-based model, and it is a weak floor."
        ),
        evidence_source_ids=["gse52778", "himes2014", "deseq2_vignette"],
    ),
    StepKnowledge(
        step="qc",
        track=AnalysisTrack.FOUNDATION,
        title="Library-size and detection quality control",
        purpose=(
            "Library size differences between samples are a technical property of "
            "sequencing depth, not biology. Quantifying them here explains why the "
            "model normalises rather than comparing raw counts."
        ),
        explain_template=(
            "Library sizes range from {{computed:qc.min_library_size}} to "
            "{{computed:qc.max_library_size}} counts, a ratio of "
            "{{computed:qc.depth_ratio}}. Detected genes per sample range from "
            "{{computed:qc.min_detected_genes}} to "
            "{{computed:qc.max_detected_genes}}."
        ),
        what_to_observe=(
            "Look for a sample far below the others in depth or detected genes. "
            "A single outlying library can dominate the variance structure."
        ),
        evidence_source_ids=["deseq2_vignette", "love2014"],
    ),
    StepKnowledge(
        step="filter",
        track=AnalysisTrack.FOUNDATION,
        title="Low-information gene filtering",
        purpose=(
            "Genes with almost no counts anywhere cannot support inference and "
            "only enlarge the multiple-testing correction. Removing them raises "
            "power without choosing which biology survives."
        ),
        explain_template=(
            "Keeping genes with at least {{param:bulk.filter.min_counts}} counts "
            "in at least {{param:bulk.filter.min_samples}} samples retained "
            "{{computed:filter.n_genes_kept}} of "
            "{{computed:filter.n_genes_input}} genes."
        ),
        what_to_observe=(
            "The filter should remove a large block of near-zero genes without "
            "touching genes that are strongly expressed in only one group."
        ),
        evidence_source_ids=["love2014", "deseq2_vignette"],
        caveats=[
            "Filtering is applied before testing and independently of the "
            "condition labels, so it does not bias the reported p-values."
        ],
    ),
    StepKnowledge(
        step="exploratory",
        track=AnalysisTrack.FOUNDATION,
        title="Sample-level structure: PCA and correlation",
        purpose=(
            "Before testing, look at whether samples group by the condition of "
            "interest or by something else. Structure driven by batch or donor "
            "must be modelled, not ignored."
        ),
        explain_template=(
            "The first principal component explains "
            "{{computed:exploratory.pc1_variance_pct}} percent of variance and the "
            "second explains {{computed:exploratory.pc2_variance_pct}} percent. "
            "Samples separate primarily by "
            "{{computed:exploratory.dominant_grouping}}."
        ),
        what_to_observe=(
            "If samples separate by donor or batch rather than by condition, the "
            "design formula must account for it before the contrast is trusted."
        ),
        evidence_source_ids=["love2014"],
    ),
    StepKnowledge(
        step="differential_expression",
        track=AnalysisTrack.FOUNDATION,
        title="Differential expression",
        purpose=(
            "Fit a count-based model per gene and test the condition contrast, "
            "correcting for multiple testing across all tested genes."
        ),
        explain_template=(
            "Using the design {{param:bulk.design.formula}} with "
            "{{param:bulk.design.reference_group}} as reference, "
            "{{computed:de.n_significant}} of {{computed:de.n_tested}} genes passed "
            "an adjusted p-value below {{param:bulk.de.fdr}}. Of those, "
            "{{computed:de.n_up}} were higher and {{computed:de.n_down}} lower in "
            "the treated group. The strongest evidence was for "
            "{{computed:de.top_genes}}."
        ),
        what_to_observe=(
            "Read effect size and evidence together. A gene can reach the "
            "significance cutoff with a fold change too small to matter, and a "
            "large fold change on a low-count gene is often unstable."
        ),
        evidence_source_ids=["love2014", "deseq2_vignette", "himes2014"],
        caveats=[
            "An adjusted p-value controls the expected proportion of false "
            "discoveries in the called set. It is not the probability that any "
            "individual gene is a true effect."
        ],
    ),
    StepKnowledge(
        step="pathway_analysis",
        track=AnalysisTrack.FOUNDATION,
        title="Pathway enrichment",
        purpose=(
            "Ask whether the differentially expressed genes fall into curated "
            "biological processes more often than expected by chance."
        ),
        explain_template=(
            "Testing {{computed:pathway.n_input_genes}} differentially expressed "
            "genes against curated gene sets, with the background restricted to "
            "the {{computed:pathway.n_background_genes}} genes detected in this "
            "matrix, {{computed:pathway.n_significant_sets}} sets passed an "
            "adjusted p-value below {{param:pathway.fdr}}. Highest ranked: "
            "{{computed:pathway.top_sets|none}}."
        ),
        what_to_observe=(
            "Check how many of your input genes actually drive each enriched set. "
            "A set called on two or three shared genes is a weak signal."
        ),
        evidence_source_ids=["liberzon2015"],
        caveats=[
            "Enrichment describes gene set membership, not pathway activity. A "
            "set can be enriched with its genes changing in opposing directions."
        ],
    ),
    # ---- Core ----------------------------------------------------------
    StepKnowledge(
        step="validate",
        track=AnalysisTrack.CORE,
        title="Validate the single-cell object",
        purpose=(
            "Confirm the object carries the cell and gene identifiers, the sample "
            "labels and the condition labels that later steps depend on. Sample "
            "identity in particular is what makes condition inference possible."
        ),
        explain_template=(
            "The object holds {{computed:validate.n_cells}} cells and "
            "{{computed:validate.n_genes}} genes from "
            "{{computed:validate.n_samples}} samples across conditions "
            "{{computed:validate.conditions}}."
        ),
        what_to_observe=(
            "Confirm there is more than one biological sample per condition. "
            "Without that, no condition-level statistical claim is possible from "
            "this dataset, however many cells it contains."
        ),
        evidence_source_ids=["gse96583", "kang2018", "squair2021"],
    ),
    StepKnowledge(
        step="cell_qc",
        track=AnalysisTrack.CORE,
        title="Cell quality control",
        purpose=(
            "Separate intact cells from empty droplets, debris, stressed cells and "
            "doublets. Every cutoff here is a judgement about what counts as a "
            "cell, and it propagates into every later result."
        ),
        explain_template=(
            "Applying a floor of {{param:sc.qc.min_genes}} genes and "
            "{{param:sc.qc.min_counts}} counts per cell, a ceiling of "
            "{{param:sc.qc.max_genes}} genes, and a mitochondrial fraction below "
            "{{param:sc.qc.max_mito_pct}} percent retained "
            "{{computed:qc.n_cells_kept}} of {{computed:qc.n_cells_input}} cells. "
            "Predicted doublets flagged: {{computed:qc.n_doublets_flagged}}."
        ),
        what_to_observe=(
            "Compare how many cells each individual filter removes, and check "
            "whether one sample loses far more cells than the others. Uneven loss "
            "across samples becomes a confounder in the condition comparison."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018", "wolock2019"],
        caveats=[
            "Doublet predictions are probabilistic. A flagged barcode is a "
            "candidate doublet, not a confirmed one.",
            "Mitochondrial thresholds are tissue-dependent. A cutoff suited to "
            "blood cells will discard viable cells in many solid tissues.",
        ],
    ),
    StepKnowledge(
        step="feature_selection",
        track=AnalysisTrack.CORE,
        title="Normalisation and highly variable genes",
        purpose=(
            "Put cells on a comparable scale, then choose the gene subset that "
            "carries the structure the embedding and clustering will see."
        ),
        explain_template=(
            "After normalisation, {{param:sc.hvg.n_top_genes}} highly variable "
            "genes were selected from {{computed:hvg.n_genes_considered}} "
            "candidates, capturing {{computed:hvg.pct_counts_in_hvgs}} percent of "
            "total counts."
        ),
        what_to_observe=(
            "If the variable gene list is dominated by mitochondrial or ribosomal "
            "genes, the embedding will largely describe cell quality rather than "
            "cell identity."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018"],
    ),
    StepKnowledge(
        step="dimensionality_reduction",
        track=AnalysisTrack.CORE,
        title="Principal components and the neighbourhood graph",
        purpose=(
            "Reduce the variable gene space to the components that carry signal, "
            "then connect each cell to its nearest neighbours. Clustering and the "
            "embedding both read this graph."
        ),
        explain_template=(
            "Retaining {{param:sc.pca.n_comps}} principal components covered "
            "{{computed:pca.cumulative_variance_pct}} percent of the variance in "
            "the selected genes, and the graph connected each cell to "
            "{{param:sc.neighbors.k}} neighbours."
        ),
        what_to_observe=(
            "Look at where the variance ratio flattens. Components beyond the "
            "elbow mostly add noise to the graph."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018"],
        caveats=[
            "A two-dimensional embedding preserves local neighbourhoods, not "
            "distances. Gaps and cluster sizes in the plot are not quantitative."
        ],
    ),
    StepKnowledge(
        step="embedding",
        track=AnalysisTrack.CORE,
        title="UMAP layout",
        purpose=(
            "Draw the neighbour graph in two dimensions so its structure can be "
            "looked at. The layout is for seeing, not for measuring: clustering "
            "reads the graph, never these coordinates."
        ),
        explain_template=(
            "UMAP placed {{computed:umap.n_cells_embedded}} cells using "
            "{{param:sc.neighbors.k}} neighbours each and a minimum distance of "
            "{{param:sc.umap.min_dist}}; {{computed:umap.n_cells_displayed}} of them "
            "are drawn."
        ),
        what_to_observe=(
            "Look for groups of cells that sit together, and then check them "
            "against the clusters and their markers. A group that looks separate "
            "here is only a candidate population until markers support it."
        ),
        evidence_source_ids=["mcinnes2018", "scanpy_docs"],
        caveats=[
            "UMAP preserves local neighbourhoods, not distances. How far apart two "
            "groups sit and how much area one covers are properties of the layout.",
            "Changing the minimum distance changes the picture without changing "
            "the neighbour graph or the clusters.",
        ],
    ),
    StepKnowledge(
        step="clustering",
        track=AnalysisTrack.CORE,
        title="Leiden clustering",
        purpose=(
            "Partition the neighbourhood graph into communities that are candidate "
            "cell populations. The number of clusters is a consequence of the "
            "resolution you choose, not a property of the tissue."
        ),
        explain_template=(
            "At resolution {{param:sc.cluster.resolution}}, the graph partitioned "
            "into {{computed:cluster.n_clusters}} clusters, the smallest holding "
            "{{computed:cluster.min_cluster_size}} cells and the largest "
            "{{computed:cluster.max_cluster_size}}."
        ),
        what_to_observe=(
            "Check whether every cluster is supported by distinct markers. "
            "Clusters that share their entire marker profile with a neighbour are "
            "usually a resolution artefact."
        ),
        evidence_source_ids=["traag2019", "scanpy_docs"],
        caveats=[
            "Cluster count is a model choice. Raising the resolution will always "
            "produce more clusters, whether or not more cell types are present."
        ],
    ),
    StepKnowledge(
        step="marker_genes",
        track=AnalysisTrack.CORE,
        title="Marker genes and annotation",
        purpose=(
            "Rank genes that distinguish each cluster so the clusters can be given "
            "biological identities, with the evidence for each identity recorded."
        ),
        explain_template=(
            "Ranking genes per cluster with the "
            "{{param:sc.markers.test}} test produced "
            "{{computed:markers.n_clusters_with_markers}} clusters carrying "
            "distinguishing genes. Top markers for the largest cluster: "
            "{{computed:markers.top_genes_largest_cluster}}."
        ),
        what_to_observe=(
            "A confident annotation needs several concordant markers, not one. "
            "Record which clusters you could not confidently name."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018", "kang2018"],
        caveats=[
            "Marker ranking compares clusters inside one dataset. It is "
            "descriptive and is not a test of any condition effect."
        ],
    ),
    StepKnowledge(
        step="composition",
        track=AnalysisTrack.CORE,
        title="Cell type composition across samples",
        purpose=(
            "Describe how cell type proportions vary between samples and "
            "conditions, and how much that variation differs between donors."
        ),
        explain_template=(
            "Across {{computed:composition.n_samples}} samples, the proportion of "
            "the most variable population ranged from "
            "{{computed:composition.min_proportion_pct}} to "
            "{{computed:composition.max_proportion_pct}} percent."
        ),
        what_to_observe=(
            "Judge the between-condition difference against the spread between "
            "donors within a condition. If donors vary as much as conditions do, "
            "the difference is not yet evidence of a condition effect."
        ),
        evidence_source_ids=["kang2018", "crowell2020"],
        caveats=[
            "Cell type proportions are compositional: an apparent rise in one "
            "population is inseparable from a fall in another."
        ],
    ),
    StepKnowledge(
        step="differential_expression",
        track=AnalysisTrack.CORE,
        title="Sample-aware differential expression",
        purpose=(
            "Test condition effects within each cell type using the sample as the "
            "unit of replication. Counts are summed per sample and cell type "
            "before modelling, so donors are compared with donors."
        ),
        explain_template=(
            "Aggregating to pseudobulk profiles per sample and cell type, with a "
            "floor of {{param:sc.de.min_cells_per_sample}} cells per profile, gave "
            "{{computed:de.n_profiles}} usable profiles across "
            "{{computed:de.n_cell_types_tested}} cell types; "
            "{{computed:de.n_profiles_dropped}} were dropped as too small. "
            "{{computed:de.n_significant}} gene and cell type combinations passed "
            "an adjusted p-value below {{param:sc.de.fdr}}."
        ),
        what_to_observe=(
            "Note which cell types could not be tested at all. Absence of a result "
            "in a rare population is a power limitation, not evidence of no effect."
        ),
        evidence_source_ids=["squair2021", "crowell2020", "kang2018"],
        caveats=[
            "Cells from one donor are not independent biological replicates. "
            "Testing conditions at the cell level treats thousands of correlated "
            "observations as independent samples and inflates false discoveries, "
            "which is why this platform tests at the sample level only."
        ],
    ),
    StepKnowledge(
        step="pathway_analysis",
        track=AnalysisTrack.CORE,
        title="Pathway enrichment per cell type",
        purpose=(
            "Summarise the sample-aware differential expression results of each "
            "cell type against curated gene sets."
        ),
        explain_template=(
            "Testing {{computed:pathway.n_input_genes}} genes against curated sets "
            "with a background of {{computed:pathway.n_background_genes}} detected "
            "genes returned {{computed:pathway.n_significant_sets}} sets below "
            "{{param:pathway.fdr}}. Highest ranked: {{computed:pathway.top_sets|none}}."
        ),
        what_to_observe=(
            "Compare enriched sets between cell types. A response shared across "
            "every population suggests a global effect rather than a cell type "
            "specific one."
        ),
        evidence_source_ids=["liberzon2015"],
        caveats=[
            "Enrichment describes gene set membership, not pathway activity."
        ],
    ),
    # ---- Core extension: cell-cell communication -----------------------
    StepKnowledge(
        step="communication",
        track=AnalysisTrack.CORE,
        title="Ligand and receptor screen",
        purpose=(
            "Summarise which curated ligands and receptors are detectable in each "
            "annotated cell type. Everything downstream is built on this "
            "summary, so a cell type with too few cells is set aside rather than "
            "summarised badly."
        ),
        explain_template=(
            "Of {{computed:expression.n_pairs_in_database}} curated pairs, "
            "{{computed:expression.n_pairs_measurable}} have both genes present "
            "in this dataset. Cell types with enough cells to summarise: "
            "{{computed:expression.cell_types}}."
        ),
        what_to_observe=(
            "Note which cell types were set aside for low cell numbers. A "
            "population that is absent from this table cannot appear in any "
            "interaction result, which is a limit of the data rather than a "
            "biological finding."
        ),
        evidence_source_ids=["scanpy_docs", "efremova2020"],
        caveats=[
            "Detection in single-cell data is sparse. A gene missing here was not "
            "detected; it was not necessarily unexpressed.",
        ],
    ),
    StepKnowledge(
        step="candidate_pairs",
        track=AnalysisTrack.CORE,
        title="Candidate interactions",
        purpose=(
            "Score every ordered pair of cell types for co-expression of a ligand "
            "and its receptor, and compare each score against a null built by "
            "shuffling which cell belongs to which type."
        ),
        explain_template=(
            "{{computed:interactions.n_tested}} ligand-receptor and cell type "
            "combinations cleared the detection floor and were tested; "
            "{{computed:interactions.n_significant}} passed an adjusted p-value "
            "below {{param:comm.interaction_fdr}}. Highest ranked: "
            "{{computed:interactions.top_interactions|none}}."
        ),
        what_to_observe=(
            "Check whether the source and target populations could plausibly meet "
            "in the tissue. Co-expression in a dissociated sample says nothing "
            "about whether two cells were ever near each other."
        ),
        evidence_source_ids=["efremova2020", "armingol2021"],
        caveats=[
            "These are inferred candidate interactions, never demonstrated "
            "physical signalling. The test shows the co-expression is unlikely "
            "under a random assignment of cells to types, and nothing more.",
            "Dissociation destroys tissue architecture, so the data cannot "
            "distinguish neighbouring cells from cells that never met.",
        ],
    ),
    StepKnowledge(
        step="condition_comparison",
        track=AnalysisTrack.CORE,
        title="Comparison between conditions",
        purpose=(
            "Ask whether the candidate interactions look different between "
            "conditions, keeping the sample as the unit of replication."
        ),
        explain_template=(
            "{{computed:comm_condition.n_compared}} candidate interactions were "
            "compared across conditions "
            "{{computed:comm_condition.conditions}}, with the sample as the "
            "replication unit."
        ),
        what_to_observe=(
            "Judge any difference against how much donors within one condition "
            "differ from each other. A shift smaller than the donor spread is not "
            "a condition effect."
        ),
        evidence_source_ids=["armingol2021", "squair2021"],
        caveats=[
            "Interaction scores are summaries of expression, so a change in score "
            "can come from a change in cell composition rather than signalling.",
        ],
    ),
    StepKnowledge(
        step="candidate_mechanism",
        track=AnalysisTrack.CORE,
        title="Candidate mechanism",
        purpose=(
            "Turn the strongest candidates into explicit, testable statements, "
            "each paired with what would actually be needed to confirm it."
        ),
        explain_template=(
            "{{computed:mechanism.n_candidates}} candidate mechanisms were "
            "assembled from the interactions that passed the threshold."
        ),
        what_to_observe=(
            "For each candidate, write down the experiment that would confirm or "
            "refute it. If you cannot name one, the candidate is not yet a "
            "hypothesis."
        ),
        evidence_source_ids=["armingol2021"],
        caveats=[
            "A candidate mechanism is a proposal to test. Nothing in this module "
            "observes signalling occurring.",
        ],
    ),
    # ---- Advanced (Spatial transcriptomics) ----------------------------
    StepKnowledge(
        step="validate",
        track=AnalysisTrack.ADVANCED,
        title="Validate the spatial package",
        purpose=(
            "Confirm the package carries expression, spot coordinates and, where "
            "the platform captures on a regular array, the array positions that "
            "define which spots are neighbours."
        ),
        explain_template=(
            "The section holds {{computed:validate.n_spots}} spots and "
            "{{computed:validate.n_genes}} genes across "
            "{{computed:validate.n_sections}} section(s) from "
            "{{computed:validate.n_specimens}} specimen(s) on the "
            "{{computed:validate.platform}} platform."
        ),
        what_to_observe=(
            "Note how many specimens are present. One specimen supports "
            "description of that tissue and cannot support a claim about a "
            "population of patients, however many spots it contains."
        ),
        evidence_source_ids=["visium_docs", "moses2022"],
        caveats=[
            "Spots within a section are not independent biological replicates. "
            "The specimen is the replication unit for any condition claim.",
        ],
    ),
    StepKnowledge(
        step="spatial_qc",
        track=AnalysisTrack.ADVANCED,
        title="Spatial quality control",
        purpose=(
            "Remove spots too shallow to interpret, while checking the removed "
            "positions against the tissue image so real anatomy is not filtered "
            "away as technical failure."
        ),
        explain_template=(
            "A floor of {{param:spatial.qc.min_counts_per_spot}} counts and "
            "{{param:spatial.qc.min_genes_per_spot}} genes per spot retained "
            "{{computed:qc.n_spots_kept}} of {{computed:qc.n_spots_input}} spots, "
            "with a median of {{computed:qc.median_counts_per_spot}} counts per "
            "retained spot."
        ),
        what_to_observe=(
            "Look at where the removed spots sit. A contiguous block of removed "
            "spots is usually a fold or a tear, but it can also be genuine "
            "acellular tissue that belongs in the analysis."
        ),
        evidence_source_ids=["visium_docs"],
        caveats=[
            "Counts per spot depend on how many cells the spot happened to cover, "
            "so depth varies with tissue density as well as with quality.",
        ],
    ),
    StepKnowledge(
        step="feature_selection",
        track=AnalysisTrack.ADVANCED,
        title="Normalisation and variable genes",
        purpose=(
            "Put spots on a comparable scale and select the genes that carry the "
            "structure the spatial statistics will read."
        ),
        explain_template=(
            "{{computed:hvg.n_hvgs}} variable genes were selected from "
            "{{computed:hvg.n_genes_considered}} detected genes."
        ),
        what_to_observe=(
            "Total counts per spot track how much tissue the spot covered. If the "
            "variable genes mostly track density, the maps will show anatomy "
            "rather than expression programmes."
        ),
        evidence_source_ids=["scanpy_docs", "moses2022"],
    ),
    StepKnowledge(
        step="neighborhood_graph",
        track=AnalysisTrack.ADVANCED,
        title="Spatial neighbourhood graph",
        purpose=(
            "Define which spots count as neighbours. Every spatial statistic "
            "downstream is a statement about this graph, so the geometry must "
            "match what the platform actually measured."
        ),
        explain_template=(
            "A {{computed:graph.geometry}} neighbourhood produced "
            "{{computed:graph.n_edges}} edges with a median of "
            "{{computed:graph.median_neighbours}} neighbours per spot, and "
            "{{computed:graph.isolated_spots}} spots left isolated."
        ),
        what_to_observe=(
            "Isolated spots contribute nothing to any spatial statistic. A large "
            "number of them means the geometry does not fit the capture layout."
        ),
        evidence_source_ids=["visium_docs", "palla2022"],
        caveats=[
            "Only geometries compatible with the capture platform are offered. "
            "Imposing a distance rule on a regular array invents adjacencies the "
            "assay never measured.",
        ],
    ),
    StepKnowledge(
        step="spatially_variable_genes",
        track=AnalysisTrack.ADVANCED,
        title="Spatially variable genes",
        purpose=(
            "Rank genes by how strongly their expression is organised in space, "
            "using spatial autocorrelation against a permutation null."
        ),
        explain_template=(
            "Of {{computed:svg.n_tested}} variable genes, "
            "{{computed:svg.n_significant}} showed spatial structure below an "
            "adjusted p-value of {{param:pathway.fdr}}. Most strongly structured: "
            "{{computed:svg.top_genes}}."
        ),
        what_to_observe=(
            "Compare each gene map against the tissue image. Structure that "
            "follows the section outline rather than the anatomy is usually a "
            "depth or edge artefact."
        ),
        evidence_source_ids=["palla2022", "moses2022"],
        caveats=[
            "Spatial autocorrelation measures structure, not importance, and its "
            "value depends on the neighbourhood geometry you chose.",
        ],
    ),
    StepKnowledge(
        step="spatial_domains",
        track=AnalysisTrack.ADVANCED,
        title="Spatial domains",
        purpose=(
            "Group spots that are both similar in expression and physically "
            "adjacent, producing contiguous candidate regions rather than "
            "scattered clusters."
        ),
        explain_template=(
            "At resolution {{param:spatial.domains.resolution}}, the section "
            "partitioned into {{computed:domains.n_domains}} domains, the "
            "smallest holding {{computed:domains.min_domain_size}} spots and the "
            "largest {{computed:domains.max_domain_size}}."
        ),
        what_to_observe=(
            "Overlay the domains on the tissue image. A domain that does not "
            "correspond to anything visible in the histology needs a stronger "
            "justification than one that traces a recognisable structure."
        ),
        evidence_source_ids=["traag2019", "palla2022"],
        caveats=[
            "A spatial domain is a model output. It becomes an anatomical region "
            "only when you annotate it against the image and marker evidence.",
        ],
    ),
    StepKnowledge(
        step="reference_mapping",
        track=AnalysisTrack.ADVANCED,
        title="Reference mapping and deconvolution",
        purpose=(
            "Estimate which cell types make up the mixture captured under each "
            "spot, using a single-cell reference from a compatible tissue."
        ),
        explain_template=(
            "Reference mapping performed: {{computed:mapping.performed}}. "
            "Estimate kind: {{computed:mapping.estimate_kind}}."
        ),
        what_to_observe=(
            "Check that the reference covers the cell types you expect in this "
            "tissue. Deconvolution can only report cell types the reference "
            "contains, and it will distribute a missing type across the others."
        ),
        evidence_source_ids=["kleshchevnikov2022"],
        caveats=[
            "Spot-level cell type estimates are probabilistic and compositional. "
            "They describe the mixture under a spot and are never the identity of "
            "a single cell.",
            "An incompatible reference produces confident-looking abundances for "
            "cell types that were never in the section.",
        ],
    ),
    StepKnowledge(
        step="neighborhood_analysis",
        track=AnalysisTrack.ADVANCED,
        title="Neighbourhood analysis",
        purpose=(
            "Ask which domains sit next to each other more often than a random "
            "arrangement of the same domains would produce."
        ),
        explain_template=(
            "{{computed:neighborhood.n_pairs_tested}} domain pairs were tested "
            "and {{computed:neighborhood.n_significant}} were adjacent more often "
            "than chance predicts."
        ),
        what_to_observe=(
            "Adjacency between a domain and itself is expected, because domains "
            "are contiguous by construction. The informative rows are pairs of "
            "different domains."
        ),
        evidence_source_ids=["palla2022"],
        caveats=[
            "Adjacency describes tissue organisation. Two domains sitting "
            "together is not evidence that they interact.",
        ],
    ),
    StepKnowledge(
        step="region_comparison",
        track=AnalysisTrack.ADVANCED,
        title="Region comparison",
        purpose=(
            "Describe how expression differs between two regions of the section, "
            "as the starting point for a hypothesis about what distinguishes them."
        ),
        explain_template=(
            "Comparing {{computed:region.regionA}} against "
            "{{computed:region.regionB}} gave {{computed:region.n_significant}} "
            "genes below an adjusted p-value of {{param:pathway.fdr}}. Inference "
            "scope: {{computed:region.inference_scope}}."
        ),
        what_to_observe=(
            "Ask whether the difference could be explained by tissue density or "
            "capture depth rather than by a change in the cells themselves."
        ),
        evidence_source_ids=["moses2022", "palla2022"],
        caveats=[
            "Spots within one section are not independent biological replicates. "
            "Where the package holds a single specimen, this comparison is "
            "descriptive and hypothesis-generating; it does not support a "
            "population-level claim.",
        ],
    ),
    StepKnowledge(
        step="pathway_analysis",
        track=AnalysisTrack.ADVANCED,
        title="Pathway enrichment",
        purpose=(
            "Summarise the genes that distinguish the compared regions against "
            "curated gene sets."
        ),
        explain_template=(
            "Testing {{computed:pathway.n_input_genes}} region-distinguishing "
            "genes against curated sets with a background of "
            "{{computed:pathway.n_background_genes}} detected genes returned "
            "{{computed:pathway.n_significant_sets}} sets below "
            "{{param:pathway.fdr}}. Highest ranked: {{computed:pathway.top_sets|none}}."
        ),
        what_to_observe=(
            "Enrichment here inherits the limits of the region comparison it was "
            "built from, including its inference scope."
        ),
        evidence_source_ids=["liberzon2015"],
        caveats=[
            "Enrichment describes gene set membership, not pathway activity.",
        ],
    ),
]

KNOWLEDGE: Dict[str, StepKnowledge] = {f"{s.track.value}:{s.step}": s for s in _STEPS}


def get(track: AnalysisTrack, step: str) -> StepKnowledge:
    try:
        return KNOWLEDGE[f"{track.value}:{step}"]
    except KeyError:
        raise KeyError(
            f"No reviewed Copilot content for step '{step}' on the "
            f"{track.value} track. The Copilot does not generate content for "
            f"steps it has no approved knowledge entry for."
        )


def steps_for(track: AnalysisTrack) -> List[StepKnowledge]:
    return [s for s in _STEPS if s.track is track]
