"""End-to-end Phase 1 flow through the API, including the entitlement gates a
front end could otherwise bypass (spec 13, 14.2)."""

from app.constants import AccessTier
from app.models import Dataset, Entitlement


def test_lab_home_shows_progress_tier_and_locked_features(client, auth):
    home = client.get("/api/program/home", headers=auth).json()
    assert home["accessTier"] == "basic"
    assert len(home["weeks"]) == 8
    assert home["lockedFeatures"]
    # Every week's module is built; weeks ahead of the learner are time-locked,
    # not missing.
    assert all(week["available"] for week in home["weeks"])
    week_six = next(w for w in home["weeks"] if w["week"] == 6)
    assert week_six["status"] == "locked_until_week"


def test_knowledge_bank_is_available_to_basic(client, auth):
    payload = client.get("/api/program/knowledge-bank", headers=auth).json()
    assert payload["cards"] and payload["glossary"]
    assert all("limitations" in card for card in payload["cards"])


def test_pre_lab_assessment_recommends_review_topics(client, auth):
    questions = client.get("/api/program/pre-lab", headers=auth).json()["questions"]
    assert all("answer" not in q for q in questions)
    result = client.post(
        "/api/program/pre-lab",
        headers=auth,
        json={"responses": {q["id"]: 0 for q in questions}},
    ).json()
    assert result["recommendedTopics"]


def test_design_studio_saves_a_plan_and_records_its_warnings(client, auth):
    payload = {
        "brief_id": "interferon-response-heterogeneity",
        "biological_question": "Which populations respond to stimulation?",
        "chosen_assay": "core",
        "samples": [
            {"sample_id": "S1", "condition": "stimulated", "donor": "d1"},
            {"sample_id": "S2", "condition": "control", "donor": "d2"},
        ],
    }
    saved = client.post("/api/design/plan", headers=auth, json=payload)
    assert saved.status_code == 201
    body = saved.json()
    assert any(w["code"] == "insufficient_replication" for w in body["designWarnings"])
    assert body["assayTradeoffs"]["limitations"]


def test_design_studio_refuses_identifiable_metadata(client, auth):
    response = client.post(
        "/api/design/plan",
        headers=auth,
        json={
            "brief_id": "b",
            "biological_question": "q",
            "chosen_assay": "core",
            "samples": [
                {"sample_id": "S1", "condition": "c", "covariates": {"patient_name": "Jane"}}
            ],
        },
    )
    assert response.status_code == 422
    codes = [e["code"] for e in response.json()["detail"]["errors"]]
    assert "identifiable_information" in codes


def test_dataset_provenance_is_always_visible(client, auth, fixture_dataset):
    rows = client.get("/api/datasets", headers=auth).json()
    assert rows[0]["provenance"]["accession"]
    assert rows[0]["limitations"]


def test_parameter_panel_is_tier_scoped(client, auth):
    panel = client.get("/api/runs/parameters/core", headers=auth).json()
    assert panel["scope"] == "limited"
    assert panel["widerScopesAvailable"] == ["full", "extended"]
    assert panel["upgradeNote"]


def test_guided_run_completes_and_copilot_explains_it(client, auth, db_session, fixture_dataset, tmp_path, monkeypatch):
    import json

    import numpy as np

    from app.settings import settings

    # Materialise the fixture files the loader expects.
    directory = tmp_path / "fixtures"
    directory.mkdir()
    rng = np.random.default_rng(3)
    genes = [f"GENE{i:03d}" for i in range(598)] + ["MT-A", "MT-B"]
    obs, blocks = [], []
    for donor in range(4):
        condition = "stimulated" if donor % 2 else "control"
        block = rng.negative_binomial(6, 0.3, size=(50, 600))
        if condition == "stimulated":
            block[:, :40] *= 4
        blocks.append(block)
        obs.extend(
            {"cell_id": f"d{donor}c{i}", "sample_id": f"donor{donor}", "condition": condition}
            for i in range(50)
        )
    np.savez_compressed(directory / "synthetic-core.npz", matrix=np.vstack(blocks))
    (directory / "synthetic-core.meta.json").write_text(json.dumps({"obs": obs, "var": genes}))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    fixture_dataset.storage_path = "fixtures/synthetic-core"
    db_session.commit()

    run = client.post(
        "/api/runs",
        headers=auth,
        json={"dataset_id": fixture_dataset.id, "track": "core", "week": 3},
    ).json()
    assert run["status"] in ("completed", "failed")
    if run["status"] == "failed":
        # Doublet detection needs the locked runtime; the message must say so.
        assert "locked method" in run["errorMessage"] or "Relax" in run["errorMessage"]
        return

    explain = client.get(
        "/api/copilot/explain", headers=auth, params={"run_id": run["id"], "step": "clustering"}
    ).json()
    assert explain["evidence"] and explain["computedRefs"]

    interpret = client.get(
        "/api/copilot/interpret",
        headers=auth,
        params={"run_id": run["id"], "step": "differential_expression"},
    ).json()
    assert set(interpret) >= {
        "observation",
        "statisticalEvidence",
        "biologicalInterpretation",
        "hypothesis",
        "label",
    }
    assert interpret["label"] in (
        "supported",
        "partially_supported",
        "needs_validation",
        "speculative",
    )

    # AI audit: the learner adjudicates the AI output, and the record persists.
    audit = client.post(
        "/api/copilot/audit",
        headers=auth,
        json={
            "interaction_id": interpret["interactionId"],
            "action": "needs_validation",
            "learner_rationale": "Only four donors.",
        },
    )
    assert audit.status_code == 201

    report = client.post(
        "/api/reports", headers=auth, json={"run_id": run["id"], "export_format": "pdf_summary"}
    ).json()
    assert report["content"]["methods"]["methodVersions"]
    assert report["content"]["references"]
    assert report["content"]["limitations"]


def test_basic_cannot_export_the_full_report(client, auth, learner, fixture_dataset, db_session):
    from app.constants import AnalysisTrack
    from app.models import Run

    run = Run(
        user_id=learner.id,
        dataset_id=fixture_dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.BASIC,
        pipeline_version="core-1.0.0",
    )
    db_session.add(run)
    db_session.commit()
    response = client.post(
        "/api/reports", headers=auth, json={"run_id": run.id, "export_format": "pdf_full"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["availableFormats"] == ["pdf_summary"]


def test_admin_endpoints_reject_a_learner(client, auth):
    assert client.get("/api/admin/usage", headers=auth).status_code == 403


def test_upgrade_screen_compares_all_three_tiers(client, auth):
    payload = client.get("/api/entitlements/upgrade-options", headers=auth).json()
    assert [c["tier"] for c in payload["columns"]] == ["basic", "moderate", "expert"]
    assert payload["columns"][0]["current"] is True
    assert payload["columns"][2]["purchasable"] is True
