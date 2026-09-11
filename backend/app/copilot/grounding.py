"""Structural guarantee that the Copilot cannot fabricate.

Spec 8/14.4. Rather than instructing a model not to invent numbers, genes or
citations, the Copilot composes every response from curated templates whose
only variable content is a *reference* to something that already exists:

    ``{{computed:de.n_significant}}``  -> an actual pipeline output for this run
    ``{{param:sc.cluster.resolution}}`` -> a validated parameter from the registry
    ``{{method:bulk_statistics.version}}`` -> a locked method constant

Rendering resolves those references and records every literal it substituted.
``verify_grounded`` then re-reads the finished text and fails closed if it
contains any number or gene-shaped token that did not come from one of those
sources. A template with a hard-typed number or gene name therefore cannot ship.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from app.constants import LOCKED_METHODS
from app.copilot import evidence

#: A reference may name a fallback in words for an empty value, as in
#: ``{{computed:pathway.top_sets|none}}``. The fallback is lower-case words only,
#: so it can carry no number or gene symbol the verifier would have to trust.
_REF = re.compile(r"\{\{(computed|param|method):([A-Za-z0-9_.\[\]-]+)(?:\|([a-z][a-z ]*))?\}\}")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?:[eE]-?\d+)?%?")
_GENE_SHAPED = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:-[A-Z0-9]+)?\b")

#: Uppercase tokens that are domain vocabulary, not gene symbols. Anything
#: gene-shaped and absent from here must have arrived via a reference.
VOCABULARY: Set[str] = {
    "RNA", "DNA", "MRNA", "UMI", "UMIS", "QC", "PCA", "UMAP", "HVG", "HVGS", "DE",
    "FDR", "GLM", "BH", "PBMC", "PBMCS", "IFN", "GEO", "MSIGDB", "HGNC", "AI",
    "TEST", "SKIP", "CSV", "TSV", "PDF", "API", "URL", "DOI", "MTX", "HDF5",
    "ANNDATA", "SCANPY", "DESEQ2", "LEIDEN", "SCRUBLET", "SQUIDPY", "CELLCHAT",
    "GSEAPY", "NOTE", "WARNING", "EXPECTED", "ACTUAL", "OBSERVATION",
    "STATISTICAL", "EVIDENCE", "BIOLOGICAL", "INTERPRETATION", "HYPOTHESIS",
    "SUPPORTED", "PARTIALLY", "NEEDS", "VALIDATION", "SPECULATIVE", "MT",
}


class UngroundedOutputError(RuntimeError):
    """Raised when a Copilot response contains content traceable to nothing."""


@dataclass
class Grounded:
    """A rendered Copilot response and the full provenance of its content."""

    text: str
    computed_refs: List[str] = field(default_factory=list)
    parameter_refs: List[str] = field(default_factory=list)
    method_refs: List[str] = field(default_factory=list)
    evidence_source_ids: List[str] = field(default_factory=list)
    #: Every literal substituted in, used by the verifier as the allowlist.
    literals: Set[str] = field(default_factory=set)


def _dig(data: Dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise UngroundedOutputError(
                f"Template referenced '{path}', which the pipeline did not compute. "
                f"The Copilot may not describe results that do not exist."
            )
    return node


def _stringify(value: Any) -> str:
    if isinstance(value, float):
        # Trim float noise without inventing precision the pipeline didn't have.
        text = f"{value:.4g}"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, (list, tuple)):
        text = ", ".join(_stringify(v) for v in value)
    else:
        text = str(value)
    return text


def _literals_of(value: Any) -> Set[str]:
    if isinstance(value, (list, tuple)):
        out: Set[str] = set()
        for item in value:
            out |= _literals_of(item)
        return out
    rendered = _stringify(value)
    #: A number inside a substituted string (the year in a citation, the digits
    #: of an accession) arrived with that string and is exactly as traceable.
    numbers = {token.lstrip("+") for token in _NUMBER.findall(rendered)}
    return {rendered, str(value)} | set(_GENE_SHAPED.findall(rendered)) | numbers


def render(
    template: str,
    computed: Dict[str, Any],
    parameters: Dict[str, Any],
    evidence_source_ids: List[str],
) -> Grounded:
    """Resolve references in ``template`` and record where each literal came from.

    Citations are validated against the approved registry here, so an unknown
    reference raises before the response can reach a learner.
    """
    evidence.resolve(evidence_source_ids)  # raises on anything unapproved

    result = Grounded(text="", evidence_source_ids=list(evidence_source_ids))

    def _replace(match: "re.Match") -> str:
        kind, path, fallback = match.group(1), match.group(2), match.group(3)
        if kind == "computed":
            value = _dig(computed, path)
            result.computed_refs.append(path)
        elif kind == "param":
            if path not in parameters:
                raise UngroundedOutputError(
                    f"Template referenced parameter '{path}', which was not part "
                    f"of this run's validated parameter set."
                )
            value = parameters[path]
            result.parameter_refs.append(path)
        else:
            value = _dig(LOCKED_METHODS, path)
            result.method_refs.append(path)
        if fallback and (value is None or value == "" or value == [] or value == ()):
            return fallback
        result.literals |= _literals_of(value)
        return _stringify(value)

    result.text = _REF.sub(_replace, template)
    verify_grounded(result)
    return result


def verify_grounded(grounded: Grounded) -> None:
    """Fail closed on any number or gene symbol with no traceable origin."""
    allowed = {lit.rstrip("%") for lit in grounded.literals}

    for token in _NUMBER.findall(grounded.text):
        if token.rstrip("%").lstrip("+") not in allowed:
            raise UngroundedOutputError(
                f"Response contains the value '{token}', which came from neither a "
                f"computed pipeline output nor a validated parameter. Numeric "
                f"content must be referenced, not written into a template."
            )

    for token in _GENE_SHAPED.findall(grounded.text):
        if token in VOCABULARY or token in allowed:
            continue
        raise UngroundedOutputError(
            f"Response contains the gene-like symbol '{token}', which did not come "
            f"from a computed pipeline output. Gene names must be referenced."
        )
