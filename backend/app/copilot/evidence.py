"""Approved evidence registry.

Spec 8/14.4: the Copilot may cite nothing that is not in this registry. The
seed set below is the launch content; admins add to it through the console
(spec 11) rather than the AI acquiring references at runtime.
"""

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class Source:
    id: str
    source_type: str  # dataset | publication | method | docs | database
    title: str
    reference: str
    summary: str = ""


SEED_SOURCES: List[Source] = [
    Source(
        "gse52778",
        "dataset",
        "Airway smooth muscle transcriptome, dexamethasone treatment",
        "GEO GSE52778",
        "Guided Foundation dataset: four donors, treated and untreated, paired design.",
    ),
    Source(
        "himes2014",
        "publication",
        "Himes et al., RNA-Seq transcriptome profiling identifies CRISPLD2 as a "
        "glucocorticoid responsive gene in airway smooth muscle cells",
        "PLoS ONE 2014, doi:10.1371/journal.pone.0099625",
        "Source publication for the guided Foundation dataset.",
    ),
    Source(
        "gse96583",
        "dataset",
        "PBMC scRNA-seq, control and interferon-beta stimulated",
        "GEO GSE96583",
        "Guided Core dataset: eight donors across two conditions, multiplexed 10x.",
    ),
    Source(
        "kang2018",
        "publication",
        "Kang et al., Multiplexed droplet single-cell RNA-sequencing using natural "
        "genetic variation",
        "Nature Biotechnology 2018, doi:10.1038/nbt.4042",
        "Source publication for the guided Core dataset.",
    ),
    Source(
        "love2014",
        "method",
        "Love, Huber & Anders, Moderated estimation of fold change and dispersion "
        "for RNA-seq data with DESeq2",
        "Genome Biology 2014, doi:10.1186/s13059-014-0550-8",
        "Method paper for the locked bulk statistical engine.",
    ),
    Source(
        "wolf2018",
        "method",
        "Wolf, Angerer & Theis, SCANPY: large-scale single-cell gene expression "
        "data analysis",
        "Genome Biology 2018, doi:10.1186/s13059-017-1382-1",
        "Method paper for the locked single-cell toolkit.",
    ),
    Source(
        "traag2019",
        "method",
        "Traag, Waltman & van Eck, From Louvain to Leiden: guaranteeing "
        "well-connected communities",
        "Scientific Reports 2019, doi:10.1038/s41598-019-41695-z",
        "Method paper for the locked clustering algorithm.",
    ),
    Source(
        "mcinnes2018",
        "method",
        "McInnes, Healy & Melville, UMAP: Uniform Manifold Approximation and "
        "Projection for Dimension Reduction",
        "arXiv 2018, arXiv:1802.03426",
        "Method paper for the locked embedding algorithm.",
    ),
    Source(
        "wolock2019",
        "method",
        "Wolock, Lopez & Klein, Scrublet: computational identification of cell "
        "doublets in single-cell transcriptomic data",
        "Cell Systems 2019, doi:10.1016/j.cels.2018.11.005",
        "Method paper for the locked doublet detection method.",
    ),
    Source(
        "squair2021",
        "publication",
        "Squair et al., Confronting false discoveries in single-cell differential "
        "expression",
        "Nature Communications 2021, doi:10.1038/s41467-021-25960-2",
        "Evidence for the platform rule that condition inference must be "
        "sample-aware: cell-level tests inflate false discoveries.",
    ),
    Source(
        "crowell2020",
        "method",
        "Crowell et al., muscat detects subpopulation-specific state transitions "
        "from multi-sample multi-condition single-cell transcriptomics data",
        "Nature Communications 2020, doi:10.1038/s41467-020-19894-4",
        "Method basis for pseudobulk aggregation by sample and cell type.",
    ),
    Source(
        "liberzon2015",
        "database",
        "Liberzon et al., The Molecular Signatures Database Hallmark gene set "
        "collection",
        "Cell Systems 2015, doi:10.1016/j.cels.2015.12.004",
        "Source of the locked pathway enrichment gene sets.",
    ),
    Source(
        "efremova2020",
        "method",
        "Efremova et al., CellPhoneDB: inferring cell-cell communication from "
        "combined expression of multi-subunit ligand-receptor complexes",
        "Nature Protocols 2020, doi:10.1038/s41596-020-0292-x",
        "Method paper for the locked cell-communication statistic and the "
        "curated interaction database it reads.",
    ),
    Source(
        "armingol2021",
        "publication",
        "Armingol et al., Deciphering cell-cell interactions and communication "
        "from gene expression",
        "Nature Reviews Genetics 2021, doi:10.1038/s41576-020-00292-x",
        "Review setting out what co-expression-based communication inference "
        "can and cannot establish.",
    ),
    Source(
        "palla2022",
        "method",
        "Palla et al., Squidpy: a scalable framework for spatial omics analysis",
        "Nature Methods 2022, doi:10.1038/s41592-021-01358-2",
        "Method reference for spatial neighbourhood graphs, spatial "
        "autocorrelation and neighbourhood enrichment.",
    ),
    Source(
        "moses2022",
        "publication",
        "Moses & Pachter, Museum of spatial transcriptomics",
        "Nature Methods 2022, doi:10.1038/s41592-022-01409-2",
        "Survey of spatial transcriptomics platforms and their resolution and "
        "replication limits.",
    ),
    Source(
        "kleshchevnikov2022",
        "method",
        "Kleshchevnikov et al., Cell2location maps fine-grained cell types in "
        "spatial transcriptomics",
        "Nature Biotechnology 2022, doi:10.1038/s41587-021-01139-4",
        "Method paper for the locked spatial deconvolution method; its output is "
        "cell type abundance per spot, which is compositional.",
    ),
    Source(
        "visium_docs",
        "docs",
        "Visium spatial gene expression — official platform documentation",
        "https://www.10xgenomics.com/support/spatial-gene-expression",
        "Official documentation for the capture array geometry and spot "
        "resolution of the guided Advanced dataset.",
    ),
    Source(
        "scanpy_docs",
        "docs",
        "Scanpy official documentation — preprocessing and quality control",
        "https://scanpy.readthedocs.io/",
        "Official documentation for the locked single-cell toolkit.",
    ),
    Source(
        "deseq2_vignette",
        "docs",
        "DESeq2 Bioconductor vignette — analysing RNA-seq data for differential "
        "gene expression",
        "https://bioconductor.org/packages/DESeq2/",
        "Official documentation for the locked bulk statistical engine.",
    ),
]

REGISTRY: Dict[str, Source] = {s.id: s for s in SEED_SOURCES}


class UnknownEvidenceError(ValueError):
    """An AI output referenced a citation that is not in the approved registry."""


def get(source_id: str) -> Source:
    try:
        return REGISTRY[source_id]
    except KeyError:
        raise UnknownEvidenceError(
            f"Citation '{source_id}' is not in the approved evidence registry."
        )


def resolve(source_ids: Iterable[str]) -> List[dict]:
    """Expand citation ids into full references, rejecting anything unapproved."""
    return [asdict(get(sid)) for sid in source_ids]
