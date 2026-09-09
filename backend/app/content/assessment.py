"""Week assessment concept bank (spec 9.11, 13).

The week assessment has three components; this file holds only the first, the
concept questions. The other two — analytical decisions and interpretation
quality — are not asked, they are measured from what the learner actually
recorded, in ``app.core.assessment``.

Every answer here matches a stance the Knowledge Bank teaches and the pipelines
enforce, so the assessment cannot contradict the platform.
"""

from typing import Dict, List

#: week -> questions. `answer` and `explanation` are stripped before serving.
WEEK_QUESTIONS: Dict[int, List[dict]] = {
    1: [
        {
            "id": "w1-replication",
            "prompt": "Four donors are each split into a treated and an untreated flask. What is the replication unit for the treatment comparison?",
            "options": ["The flask", "The donor", "The cell", "The sequencing lane"],
            "answer": "The donor",
            "explanation": "Two flasks from one donor share that donor's genetics and history, so they are not independent instances of the condition.",
            "reviewTopic": "What counts as a replicate",
        },
        {
            "id": "w1-confounding",
            "prompt": "Every treated sample was processed in batch 1 and every untreated sample in batch 2. What can the analysis conclude about treatment?",
            "options": [
                "Treatment effects, as normal",
                "Nothing separable from batch",
                "Treatment effects, if batch is added to the model",
                "Only effects larger than the batch effect",
            ],
            "answer": "Nothing separable from batch",
            "explanation": "Batch and condition are completely confounded: no model can separate two variables that move together perfectly.",
            "reviewTopic": "Design and confounding",
        },
        {
            "id": "w1-assay",
            "prompt": "The question is which cell populations change proportion between conditions. Which assay answers it?",
            "options": ["Bulk RNA-seq", "Single-cell RNA-seq", "Spatial transcriptomics", "Any of them"],
            "answer": "Single-cell RNA-seq",
            "explanation": "Bulk averages over cells, so it cannot report composition. Spatial adds location but is not required by the question.",
            "reviewTopic": "Choosing an assay",
        },
    ],
    2: [
        {
            "id": "w2-zero",
            "prompt": "In a single-cell count matrix, what does a zero most reliably mean?",
            "options": [
                "The gene is switched off in that cell",
                "The transcript was not detected in that cell",
                "The cell is dead",
                "The gene is not expressed in that tissue",
            ],
            "answer": "The transcript was not detected in that cell",
            "explanation": "Only a fraction of transcripts in a cell are captured, so absence of evidence is not evidence of absence.",
            "reviewTopic": "How single-cell data is generated",
        },
        {
            "id": "w2-qc",
            "prompt": "A strict mitochondrial-fraction cutoff removes 30% of cells. What is the risk?",
            "options": [
                "None; stricter QC is always safer",
                "Losing a genuinely high-mitochondrial cell type",
                "Inflating the number of genes detected",
                "Making clustering deterministic",
            ],
            "answer": "Losing a genuinely high-mitochondrial cell type",
            "explanation": "Metabolically active populations carry high mitochondrial content; a fixed cutoff can delete a real population.",
            "reviewTopic": "Quality control thresholds",
        },
        {
            "id": "w2-normalisation",
            "prompt": "Why is a count matrix normalised before comparing cells?",
            "options": [
                "To remove biological variation",
                "To make sequencing depth comparable between cells",
                "To force a normal distribution",
                "To remove doublets",
            ],
            "answer": "To make sequencing depth comparable between cells",
            "explanation": "Cells are sequenced to different depths; without normalisation depth would dominate every comparison.",
            "reviewTopic": "Normalisation",
        },
    ],
    3: [
        {
            "id": "w3-clusters",
            "prompt": "You raise the clustering resolution and get four more clusters. What follows?",
            "options": [
                "Four more cell types are present",
                "The earlier clustering was wrong",
                "The graph was partitioned more finely; whether the new clusters are real populations depends on their markers",
                "The data needs reprocessing",
            ],
            "answer": "The graph was partitioned more finely; whether the new clusters are real populations depends on their markers",
            "explanation": "Resolution is a model choice. A cluster becomes a cell type only once it shows consistent markers.",
            "reviewTopic": "Clusters are a model output",
        },
        {
            "id": "w3-umap",
            "prompt": "Two clusters sit far apart on the UMAP. What does that distance license you to say?",
            "options": [
                "They are very different cell types",
                "Little: UMAP distances are not a quantitative measure of similarity",
                "They came from different samples",
                "One is a doublet cluster",
            ],
            "answer": "Little: UMAP distances are not a quantitative measure of similarity",
            "explanation": "UMAP preserves local neighbourhoods, not global distances; between-cluster separation is not interpretable as magnitude.",
            "reviewTopic": "Dimensionality reduction",
        },
        {
            "id": "w3-annotation",
            "prompt": "What makes a cluster annotation defensible?",
            "options": [
                "It matches the expected cell type",
                "Marker genes consistent with a known population, with the confidence stated",
                "It has the most cells",
                "The clustering resolution was left at default",
            ],
            "answer": "Marker genes consistent with a known population, with the confidence stated",
            "explanation": "An annotation is a claim about identity and needs its evidence and its uncertainty recorded.",
            "reviewTopic": "Annotation confidence",
        },
    ],
    4: [
        {
            "id": "w4-padj",
            "prompt": "A gene has an adjusted p-value of 0.03. What does that mean?",
            "options": [
                "There is a 3% chance this gene is a false positive",
                "The gene changed by 3%",
                "Among genes called at this threshold, roughly 3% are expected to be false discoveries",
                "The effect is small",
            ],
            "answer": "Among genes called at this threshold, roughly 3% are expected to be false discoveries",
            "explanation": "An adjusted p-value is a property of the called set, not the probability that one gene is a true effect.",
            "reviewTopic": "Adjusted p-values",
        },
        {
            "id": "w4-pseudoreplication",
            "prompt": "Testing conditions cell-by-cell across two donors gives thousands of tiny p-values. Why is that misleading?",
            "options": [
                "The test is too conservative",
                "Cells within a donor are not independent replicates of the condition",
                "Fold changes are inflated by normalisation",
                "The wrong multiple-testing correction was used",
            ],
            "answer": "Cells within a donor are not independent replicates of the condition",
            "explanation": "Treating cells as replicates counts the same donor thousands of times, so the significance is manufactured by the sample size.",
            "reviewTopic": "Sample-aware differential expression",
        },
        {
            "id": "w4-enrichment",
            "prompt": "A pathway is enriched in your differentially expressed genes. What can you say?",
            "options": [
                "The pathway is activated",
                "Your gene list overlaps that curated set more than chance predicts",
                "The pathway is inhibited",
                "The pathway drives the phenotype",
            ],
            "answer": "Your gene list overlaps that curated set more than chance predicts",
            "explanation": "Enrichment describes set membership. Direction and activity are separate claims needing separate evidence.",
            "reviewTopic": "Pathway interpretation",
        },
    ],
    5: [
        {
            "id": "w5-inferred",
            "prompt": "A ligand-receptor pair scores highly between two cell types. What have you shown?",
            "options": [
                "The two cell types are signalling",
                "A candidate interaction consistent with co-expression, not demonstrated signalling",
                "The receptor is activated",
                "The cells are physically adjacent",
            ],
            "answer": "A candidate interaction consistent with co-expression, not demonstrated signalling",
            "explanation": "Expression of a ligand and a receptor is compatible with signalling; it does not demonstrate that signalling occurred.",
            "reviewTopic": "Inferred communication",
        },
        {
            "id": "w5-confirm",
            "prompt": "What would move a candidate mechanism from hypothesis towards demonstration?",
            "options": [
                "A larger dataset",
                "A perturbation experiment targeting the pair, with a measured functional readout",
                "A lower p-value",
                "Repeating the analysis with another tool",
            ],
            "answer": "A perturbation experiment targeting the pair, with a measured functional readout",
            "explanation": "Only an intervention with a functional outcome tests whether the inferred interaction is doing anything.",
            "reviewTopic": "From candidate to mechanism",
        },
    ],
    6: [
        {
            "id": "w6-spot",
            "prompt": "Deconvolution reports 40% T cells in a Visium spot. What is that number?",
            "options": [
                "The identity of the cell at that spot",
                "A compositional estimate over the several cells the spot covers",
                "The probability the spot contains a T cell",
                "The fraction of transcripts that are T-cell specific",
            ],
            "answer": "A compositional estimate over the several cells the spot covers",
            "explanation": "A spot covers multiple cells, so its cell-type estimate is a proportion, never a single-cell identity.",
            "reviewTopic": "Spot-level estimates",
        },
        {
            "id": "w6-single-section",
            "prompt": "Your teaching dataset has one section from one specimen. How should a region comparison be labelled?",
            "options": [
                "Population-level inference",
                "Descriptive and hypothesis-generating",
                "Confirmatory, if the p-value is small",
                "Statistically significant",
            ],
            "answer": "Descriptive and hypothesis-generating",
            "explanation": "With one specimen there is no biological replication, so between-region differences cannot generalise.",
            "reviewTopic": "Single-specimen limits",
        },
    ],
    7: [
        {
            "id": "w7-role",
            "prompt": "The Copilot reports a cluster count you did not expect. Where did that number come from?",
            "options": [
                "The model estimated it",
                "The validated pipeline computed it for this run",
                "A reference dataset",
                "The published paper for this dataset",
            ],
            "answer": "The validated pipeline computed it for this run",
            "explanation": "The Copilot explains and interprets computed output; it never calculates or invents a result.",
            "reviewTopic": "What the Copilot is and is not",
        },
        {
            "id": "w7-audit",
            "prompt": "You disagree with an AI interpretation and mark it Reject. What is stored?",
            "options": [
                "Only your final interpretation",
                "The original AI output, its evidence, your action and your final interpretation",
                "Nothing; rejection discards the record",
                "A flag for the administrator",
            ],
            "answer": "The original AI output, its evidence, your action and your final interpretation",
            "explanation": "The audit record is append-only so the disagreement itself stays auditable.",
            "reviewTopic": "AI Research Audit",
        },
    ],
    8: [
        {
            "id": "w8-defence",
            "prompt": "A reviewer asks why you chose your clustering resolution. What is the defensible answer?",
            "options": [
                "It is the tool default",
                "It produced the clearest UMAP",
                "It was recorded with its rationale, and the alternate run shows how the conclusion moved",
                "It gave the expected number of cell types",
            ],
            "answer": "It was recorded with its rationale, and the alternate run shows how the conclusion moved",
            "explanation": "A defence rests on a recorded decision and evidence of its effect, not on the value chosen.",
            "reviewTopic": "Defending an analysis",
        },
        {
            "id": "w8-limits",
            "prompt": "Your capstone reports a candidate mechanism from one public dataset. What must the memo state?",
            "options": [
                "That the mechanism is established",
                "The limitation: one dataset, inferred communication, and the experiment that would test it",
                "Only the strongest result",
                "That further funding is required",
            ],
            "answer": "The limitation: one dataset, inferred communication, and the experiment that would test it",
            "explanation": "Stating what the work cannot conclude is part of the claim, not an appendix to it.",
            "reviewTopic": "Limitations and next steps",
        },
    ],
}


def questions_for(week: int) -> List[dict]:
    """The concept questions for a week, or week 1's if the week has none."""
    return WEEK_QUESTIONS.get(week, WEEK_QUESTIONS[1])
