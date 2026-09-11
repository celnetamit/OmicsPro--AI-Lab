"""Definition of Done: the Copilot cites approved evidence and cannot invent a
computed result, gene name or reference (spec 8, 13, 14.4)."""

import pytest

from app.constants import AnalysisTrack, InterpretationLabel
from app.copilot import evidence, knowledge, labels
from app.copilot.grounding import UngroundedOutputError, render

COMPUTED = {"de": {"n_significant": 42, "top_genes": ["CRISPLD2", "DUSP1"]}}
PARAMS = {"bulk.de.fdr": 0.05}


def test_referenced_values_are_resolved_from_the_run():
    grounded = render(
        "{{computed:de.n_significant}} genes passed {{param:bulk.de.fdr}}.",
        COMPUTED,
        PARAMS,
        ["love2014"],
    )
    assert grounded.text == "42 genes passed 0.05."
    assert grounded.computed_refs == ["de.n_significant"]


def test_a_hard_typed_number_is_rejected():
    with pytest.raises(UngroundedOutputError, match="came from neither"):
        render("About 1200 genes changed.", COMPUTED, PARAMS, [])


def test_a_hard_typed_gene_symbol_is_rejected():
    with pytest.raises(UngroundedOutputError, match="gene-like symbol"):
        render("The response is driven by GAPDH.", COMPUTED, PARAMS, [])


def test_a_referenced_gene_symbol_is_accepted():
    grounded = render("Top genes: {{computed:de.top_genes}}.", COMPUTED, PARAMS, [])
    assert "CRISPLD2" in grounded.text


def test_a_reference_to_an_uncomputed_result_is_rejected():
    with pytest.raises(UngroundedOutputError, match="did not compute"):
        render("{{computed:de.n_pathways}} pathways.", COMPUTED, PARAMS, [])


def test_an_unapproved_citation_is_rejected():
    with pytest.raises(evidence.UnknownEvidenceError):
        render("A claim.", COMPUTED, PARAMS, ["smith-et-al-2029"])


def test_every_knowledge_template_is_groundable_against_its_own_references():
    """A template with a literal result in it cannot pass this test, so one
    cannot reach a learner."""
    for entry in knowledge.KNOWLEDGE.values():
        computed, parameters = _stub_for(entry.explain_template)
        grounded = render(
            entry.explain_template, computed, parameters, entry.evidence_source_ids
        )
        assert grounded.text
        assert not grounded.text.count("{{")


def test_every_knowledge_entry_cites_only_approved_sources():
    for entry in knowledge.KNOWLEDGE.values():
        evidence.resolve(entry.evidence_source_ids)


def _stub_for(template):
    """Build a minimal computed/parameter set covering the template's references."""
    import re

    computed, parameters = {}, {}
    #: A reference may carry a fallback word (``|none``); the path is what the stub needs.
    for kind, path in re.findall(
        r"\{\{(computed|param|method):([\w.\[\]-]+)(?:\|[a-z ]+)?\}\}", template
    ):
        if kind == "computed":
            node = computed
            parts = path.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = 7
        elif kind == "param":
            parameters[path] = 7
    return computed, parameters


def test_label_vocabulary_is_closed():
    assert {r.label for _, r in labels.RULES} <= set(InterpretationLabel)
    assignment = labels.assign([])
    assert assignment["label"] == InterpretationLabel.SUPPORTED.value
    assert assignment["rationale"]


def test_worst_rule_wins_and_is_named():
    assignment = labels.assign(["few_supporting_genes", "no_replication"])
    assert assignment["label"] == InterpretationLabel.SPECULATIVE.value
    assert assignment["rule"] == "no_replication"


def test_missing_replication_downgrades_a_conclusion():
    triggered = labels.evaluate({"validate": {"min_replicates": 1}, "de": {"n_significant": 900}})
    assert "no_replication" in triggered
    assert labels.assign(triggered)["label"] == InterpretationLabel.SPECULATIVE.value


def test_cell_level_grouping_downgrades_a_conclusion():
    triggered = labels.evaluate({}, {"grouping": "per_cell"})
    assert "cell_level_inference" in triggered


def test_an_empty_reference_reads_as_its_fallback_word():
    """ "Highest ranked: ." is what an empty list rendered as before; a named
    fallback reads as a sentence and is still recorded as a reference."""
    from app.copilot.grounding import render

    empty = render("Highest ranked: {{computed:p.top|none}}.", {"p": {"top": []}}, {}, [])
    assert empty.text == "Highest ranked: none."
    assert "p.top" in empty.computed_refs

    filled = render("Highest ranked: {{computed:p.top|none}}.", {"p": {"top": ["IL7R"]}}, {}, [])
    assert filled.text == "Highest ranked: IL7R."
