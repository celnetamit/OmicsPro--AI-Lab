"""Spec 9.6: the Dataset Inspector explains a dataset before any run.

The explanation is grounded (every number and gene-like token traces to the
loaded object or the dataset record), and which analyses a design supports is
decided by rules in code, not by a model.
"""

import numpy as np
import pytest

from app.constants import AnalysisTrack
from app.copilot.dataset_brief import brief_for, compose
from app.copilot.grounding import UngroundedOutputError, render
from app.models import AiInteraction, Dataset
from app.pipelines import registry
from app.pipelines.base import DataObject


def _dataset(track, **extra) -> Dataset:
    fields = dict(
        slug="brief-test",
        name="Brief test dataset",
        track=track,
        kind="guided",
        source="GEO",
        accession="SYNTHETIC-FIXTURE-001",
        license="CC BY 4.0",
        citation="Doe et al. 2019.",
        validation_status="validated",
        limitations=["Synthetic data with no biological meaning."],
        supported_modules=[],
    )
    fields.update(extra)
    return Dataset(**fields)


def _bulk(samples_per_condition=3, paired=True, batch_is_condition=False) -> DataObject:
    obs = []
    for c, condition in enumerate(("untreated", "treated")):
        for d in range(samples_per_condition):
            obs.append(
                {
                    "sample_id": f"s{c}{d}",
                    "condition": condition,
                    "donor": f"donor{d}" if paired else f"donor{c}{d}",
                    "batch": condition if batch_is_condition else f"b{d % 2}",
                }
            )
    return DataObject(
        matrix=np.ones((50, len(obs))),
        obs=obs,
        var=[f"GENE{i}" for i in range(50)],
        track=AnalysisTrack.FOUNDATION,
    )


def _cells(donors=4, cells_each=25) -> DataObject:
    obs = [
        {
            "cell_id": f"d{d}_c{i}",
            "sample_id": f"donor{d}",
            "condition": "stimulated" if d % 2 else "control",
            "batch": "b1",
        }
        for d in range(donors)
        for i in range(cells_each)
    ]
    return DataObject(
        matrix=np.ones((len(obs), 30)),
        obs=obs,
        var=[f"GENE{i}" for i in range(30)],
        track=AnalysisTrack.CORE,
    )


def _text(payload) -> str:
    return " ".join(section["text"] for section in payload["sections"])


def _comparison_label(track) -> str:
    return next(step.label for step in registry.get(track).steps if step.publishes == "de")


def test_a_paired_bulk_design_is_recognised_and_supports_a_comparison():
    payload, _ = brief_for(_dataset(AnalysisTrack.FOUNDATION), _bulk())
    text = _text(payload)
    assert "treated, untreated" in text
    assert "the design is paired" in text
    comparison = _comparison_label(AnalysisTrack.FOUNDATION)
    assert comparison in [a["label"] for a in payload["validAnalyses"]]
    assert comparison not in [a["label"] for a in payload["notSupported"]]


def test_too_few_replicates_withholds_the_comparison_and_says_why():
    payload, _ = brief_for(_dataset(AnalysisTrack.FOUNDATION), _bulk(samples_per_condition=1))
    reasons = {a["label"]: a["reason"] for a in payload["notSupported"]}
    comparison = _comparison_label(AnalysisTrack.FOUNDATION)
    assert comparison in reasons
    assert "the smallest condition here has 1" in reasons[comparison]


def test_a_batch_confounded_with_condition_is_called_out():
    payload, _ = brief_for(_dataset(AnalysisTrack.FOUNDATION), _bulk(batch_is_condition=True))
    assert "batch and condition cannot be separated" in _text(payload)


def test_single_cell_replicates_are_samples_not_cells():
    payload, _ = brief_for(_dataset(AnalysisTrack.CORE), _cells())
    text = _text(payload)
    assert "The independent replicate is the sample, not the cell" in text
    assert "100 cells" in text
    assert _comparison_label(AnalysisTrack.CORE) in [a["label"] for a in payload["validAnalyses"]]


def test_a_single_tissue_section_is_described_as_descriptive():
    obs = [
        {"spot_id": f"s{i}", "sample_id": "section1", "x": float(i % 10), "y": float(i // 10)}
        for i in range(100)
    ]
    data = DataObject(
        matrix=np.ones((100, 20)), obs=obs, var=[f"GENE{i}" for i in range(20)],
        track=AnalysisTrack.ADVANCED,
    )
    payload, _ = brief_for(_dataset(AnalysisTrack.ADVANCED), data)
    assert "single tissue section" in _text(payload)


def test_numbers_inside_recorded_strings_are_traceable():
    payload, grounded = brief_for(_dataset(AnalysisTrack.FOUNDATION), _bulk())
    provenance = payload["sections"][0]["text"]
    assert "SYNTHETIC-FIXTURE-001" in provenance
    assert "2019" in provenance
    assert "dataset.accession" in grounded.computed_refs


def test_a_hard_typed_number_still_fails_closed():
    with pytest.raises(UngroundedOutputError):
        render("Accession {{computed:d.a}} has 7 samples.", {"d": {"a": "GSE1"}}, {}, [])


def test_the_accession_links_the_approved_dataset_source():
    payload, _ = brief_for(_dataset(AnalysisTrack.CORE, accession="GSE96583"), _cells())
    assert "gse96583" in [source["id"] for source in payload["evidence"]]


def test_the_brief_is_recorded_for_audit(db_session, learner):
    dataset = _dataset(AnalysisTrack.CORE)
    db_session.add(dataset)
    db_session.commit()
    payload = compose(db_session, learner.id, dataset, _cells())
    stored = db_session.get(AiInteraction, payload["interactionId"])
    assert stored.function == "dataset_brief"
    assert stored.prompt_context["datasetId"] == dataset.id
    assert stored.computed_refs == payload["computedRefs"]


# ------------------------------------------------------------------- API --
def _materialise_core_fixture(tmp_path, monkeypatch):
    """Write the files the loader reads for the synthetic Core fixture."""
    import json

    from app.settings import settings

    directory = tmp_path / "fixtures"
    directory.mkdir()
    rng = np.random.default_rng(3)
    genes = [f"GENE{i:03d}" for i in range(598)] + ["MT-A", "MT-B"]
    obs, blocks = [], []
    for donor in range(4):
        blocks.append(rng.negative_binomial(6, 0.3, size=(50, 600)))
        condition = "stimulated" if donor % 2 else "control"
        obs.extend(
            {"cell_id": f"d{donor}c{i}", "sample_id": f"donor{donor}", "condition": condition}
            for i in range(50)
        )
    np.savez_compressed(directory / "synthetic-core.npz", matrix=np.vstack(blocks))
    (directory / "synthetic-core.meta.json").write_text(json.dumps({"obs": obs, "var": genes}))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


def test_the_inspector_serves_the_brief_for_a_loadable_dataset(
    client, auth, fixture_dataset, tmp_path, monkeypatch
):
    _materialise_core_fixture(tmp_path, monkeypatch)
    body = client.get(f"/api/datasets/{fixture_dataset.id}/brief", headers=auth).json()
    assert body["available"] is True
    assert "200 cells" in " ".join(section["text"] for section in body["sections"])
    assert body["interactionId"]


def test_the_brief_says_so_when_the_files_are_missing(
    client, auth, fixture_dataset, tmp_path, monkeypatch
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    body = client.get(f"/api/datasets/{fixture_dataset.id}/brief", headers=auth).json()
    assert body["available"] is False
    assert body["reason"]
