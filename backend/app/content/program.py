"""The eight-week flagship program map and the Week 1 research briefs.

Week -> Live Lab module mapping is spec 3. Modules belonging to a later build
phase are marked so Lab Home can show the week as scheduled rather than broken.
"""

from app.constants import AnalysisTrack

WEEKS = [
    {
        "week": 1,
        "focus": "Biotech use-case framing and omics study design",
        "module": "design_studio",
        "moduleLabel": "Experimental Design Studio",
        "track": None,
        "phase": 1,
    },
    {
        "week": 2,
        "focus": "Data ingestion, quality control and normalisation",
        "module": "core_qc",
        "moduleLabel": "Single-cell import and quality control",
        "track": AnalysisTrack.CORE.value,
        "phase": 1,
    },
    {
        "week": 3,
        "focus": "Dimensionality reduction, clustering and annotation",
        "module": "core_clustering",
        "moduleLabel": "Clustering and annotation",
        "track": AnalysisTrack.CORE.value,
        "phase": 1,
    },
    {
        "week": 4,
        "focus": "Differential expression and pathway interpretation",
        "module": "differential_expression",
        "moduleLabel": "Sample-aware differential expression and pathways",
        "track": AnalysisTrack.CORE.value,
        "phase": 1,
    },
    {
        "week": 5,
        "focus": "Cell-cell communication",
        "module": "cell_communication",
        "moduleLabel": "Cell-Cell Communication Explorer",
        "track": AnalysisTrack.CORE.value,
        "phase": 2,
    },
    {
        "week": 6,
        "focus": "Spatial transcriptomics",
        "module": "spatial_guided",
        "moduleLabel": "Spatial guided workflow",
        "track": AnalysisTrack.ADVANCED.value,
        "phase": 2,
    },
    {
        "week": 7,
        "focus": "AI for omics workflows",
        "module": "ai_audit",
        "moduleLabel": "Omics Copilot, perturbation and AI Research Audit",
        "track": None,
        "phase": 1,
    },
    {
        "week": 8,
        "focus": "Capstone and defence",
        "module": "capstone_workspace",
        "moduleLabel": "Capstone workspace and report builder",
        "track": None,
        "phase": 3,
    },
]

RESEARCH_BRIEFS = [
    {
        "id": "asthma-steroid-response",
        "title": "Why do some airway cells respond poorly to inhaled steroids?",
        "context": (
            "A respiratory therapeutics team wants to know which genes airway "
            "smooth muscle cells change when treated with a glucocorticoid, and "
            "whether the response is consistent across donors. Cultured cells "
            "from four donors are available, each split into treated and "
            "untreated flasks."
        ),
        "decisionGoal": (
            "Decide whether a candidate response gene is worth taking into a "
            "follow-up functional study."
        ),
        "suggestedTracks": [AnalysisTrack.FOUNDATION.value],
        "designNotes": (
            "The donor is the unit of replication and treatment is applied within "
            "donor, so donor belongs in the model as well as condition."
        ),
    },
    {
        "id": "interferon-response-heterogeneity",
        "title": "Which immune cell populations drive the interferon response?",
        "context": (
            "An immunology group has peripheral blood from several donors, each "
            "sample split into a stimulated and an unstimulated aliquot. They "
            "want to know whether the response is shared across immune "
            "populations or concentrated in a few of them."
        ),
        "decisionGoal": (
            "Decide which cell population to target in a follow-up experiment."
        ),
        "suggestedTracks": [AnalysisTrack.CORE.value],
        "designNotes": (
            "The question is about populations within a sample, so a per-cell "
            "measurement is needed. The donor remains the replication unit for "
            "any statement about the condition."
        ),
    },
    {
        "id": "tumour-margin-organisation",
        "title": "How is the immune infiltrate organised around a tumour margin?",
        "context": (
            "A pathology team wants to know whether immune populations sit inside "
            "the tumour, at its margin, or excluded from it. Tissue architecture "
            "is central to the question."
        ),
        "decisionGoal": "Decide whether spatial organisation predicts treatment response.",
        "suggestedTracks": [AnalysisTrack.ADVANCED.value],
        "designNotes": (
            "Dissociating the tissue would destroy the information the question "
            "depends on. A single section supports description, not inference "
            "about a population of patients."
        ),
    },
]

ASSAY_TRADEOFFS = {
    AnalysisTrack.FOUNDATION.value: {
        "measures": "Average expression across all cells in each sample.",
        "strengths": [
            "Cheapest route to a well-powered comparison between conditions.",
            "Mature count-based statistics with a clear replication unit.",
        ],
        "limitations": [
            "Cannot tell a change within one cell population from a change in the "
            "proportions of populations.",
            "No information about where cells sit in the tissue.",
        ],
    },
    AnalysisTrack.CORE.value: {
        "measures": "Expression per individual cell, pooled across the sample.",
        "strengths": [
            "Separates cell populations and can localise a response to one of them.",
            "Reveals populations too rare to see in an average.",
        ],
        "limitations": [
            "Cells from one donor are not independent replicates, so condition "
            "claims still need several donors per group.",
            "Dissociation loses tissue architecture and biases which cell types "
            "survive.",
        ],
    },
    AnalysisTrack.ADVANCED.value: {
        "measures": "Expression at positions across an intact tissue section.",
        "strengths": [
            "Preserves tissue architecture and neighbourhood relationships.",
            "Can ask where a programme is active, not only whether it is.",
        ],
        "limitations": [
            "Most platforms measure a small region rather than a single cell, so "
            "cell type estimates per position are compositional and probabilistic.",
            "Sections are expensive, so specimen numbers are usually too small for "
            "population-level inference.",
        ],
    },
}
