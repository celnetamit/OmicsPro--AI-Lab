"""Knowledge Bank content (spec 9.2). Basic tier; part of the teaching core."""

CARDS = [
    {
        "id": "how-bulk-data-is-generated",
        "category": "How this data was generated",
        "title": "From tissue to a bulk count matrix",
        "body": (
            "Cells are lysed together, their RNA is converted to complementary "
            "DNA, fragments are sequenced, and reads are assigned to genes. What "
            "reaches you is one count per gene per sample: an average over every "
            "cell that went into the tube, weighted by how much RNA each "
            "contributed."
        ),
        "limitations": [
            "A change in the average can come from cells changing their expression "
            "or from the mixture of cells changing. Bulk data cannot separate these."
        ],
        "evidenceSourceIds": ["himes2014", "deseq2_vignette"],
    },
    {
        "id": "how-scrna-data-is-generated",
        "category": "How this data was generated",
        "title": "From tissue to a single-cell matrix",
        "body": (
            "Tissue is dissociated into a suspension, individual cells are "
            "captured with barcoded reagents, and every transcript is tagged with "
            "a cell barcode and a unique molecular identifier before "
            "amplification. Counting distinct identifiers per gene per barcode "
            "gives the matrix."
        ),
        "limitations": [
            "Dissociation is selective: fragile cell types are lost before "
            "sequencing begins, so absence from the data is not absence from the "
            "tissue.",
            "Only a fraction of transcripts in a cell are captured, so a zero "
            "means 'not detected', not 'not expressed'.",
        ],
        "evidenceSourceIds": ["kang2018", "wolf2018"],
    },
    {
        "id": "replication-unit",
        "category": "Methods",
        "title": "What counts as a replicate",
        "body": (
            "A biological replicate is an independent instance of the condition "
            "you are comparing. Two flasks from one donor share that donor's "
            "genetics and history, and thousands of cells from one sample share "
            "everything about that sample. Statistical tests assume independence, "
            "so the replication unit determines what you may conclude."
        ),
        "limitations": [
            "Treating cells as replicates produces very small p-values that do not "
            "generalise beyond the donors measured."
        ],
        "evidenceSourceIds": ["squair2021", "crowell2020"],
    },
    {
        "id": "clustering-is-a-choice",
        "category": "Methods",
        "title": "Clusters are a model output, not a discovery",
        "body": (
            "Community detection partitions a neighbourhood graph. The number of "
            "communities depends on the resolution you set. A cluster becomes a "
            "cell type only once you show it has its own consistent markers."
        ),
        "limitations": [
            "Raising the resolution always yields more clusters, whether or not "
            "more populations exist."
        ],
        "evidenceSourceIds": ["traag2019"],
    },
    {
        "id": "multiple-testing",
        "category": "Methods",
        "title": "Why adjusted p-values are used",
        "body": (
            "Testing tens of thousands of genes at once produces many small "
            "p-values by chance alone. The Benjamini-Hochberg adjustment controls "
            "the expected proportion of false discoveries among the genes you "
            "call, which is the quantity you actually care about when you take a "
            "list forward."
        ),
        "limitations": [
            "An adjusted p-value is a property of the called set, not the "
            "probability that any single gene is a true effect."
        ],
        "evidenceSourceIds": ["love2014"],
    },
    {
        "id": "enrichment-vs-activity",
        "category": "Methods",
        "title": "Enrichment describes membership, not activity",
        "body": (
            "Over-representation asks whether your gene list overlaps a curated "
            "set more than chance would predict, against a defined background. It "
            "does not measure whether the process is switched on, and it is "
            "sensitive to which background you choose."
        ),
        "limitations": [
            "A set can be enriched while its genes move in opposite directions.",
            "Curated sets are incomplete and biased toward well-studied biology.",
        ],
        "evidenceSourceIds": ["liberzon2015"],
    },
    {
        "id": "ai-role",
        "category": "Limitations",
        "title": "What the Copilot is and is not",
        "body": (
            "The Copilot explains steps, cites approved sources, proposes what-if "
            "tests, and helps you separate observation from interpretation. Every "
            "number it shows you was computed by the validated pipeline for your "
            "run. It does not compute results and it cannot cite anything outside "
            "the approved evidence registry."
        ),
        "limitations": [
            "It can only warn about the checks it has been given. Silence is not "
            "assurance that an analysis is sound."
        ],
        "evidenceSourceIds": [],
    },
]

GLOSSARY = [
    {"term": "Adjusted p-value", "definition": "A p-value corrected for the number of tests performed, controlling the expected proportion of false discoveries in the called set."},
    {"term": "Biological replicate", "definition": "An independent instance of a condition, such as a separate donor or animal, as opposed to a repeated measurement of the same one."},
    {"term": "Design formula", "definition": "The statement of which annotations the statistical model adjusts for when it estimates the effect of interest."},
    {"term": "Doublet", "definition": "A barcode that captured two cells rather than one, producing a hybrid expression profile."},
    {"term": "Highly variable gene", "definition": "A gene selected for downstream analysis because its variation across cells exceeds what the technical noise model predicts."},
    {"term": "Pseudobulk", "definition": "Counts summed across the cells of one sample and cell type, so that the sample rather than the cell is the unit of replication."},
    {"term": "Resolution", "definition": "The parameter that controls how finely community detection partitions the neighbourhood graph, and therefore how many clusters appear."},
    {"term": "Unique molecular identifier", "definition": "A random tag attached to a transcript before amplification, so duplicated reads can be collapsed back to one original molecule."},
]
