"""Spec 11, 12, 14 and 17: commercial terms, issue reports, week unlock.

Spec 12: "Pricing, duration, run allowance and expiry must be configurable in
admin; do not hard-code commercial values in the scientific application."
"""

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.models import Enrollment, Run


# ---------------------------------------------------------- commercial terms --
def test_the_catalogue_is_read_from_admin_settings(client, admin_auth, auth):
    changed = client.put(
        "/api/admin/commercial/catalogue",
        headers=admin_auth,
        json={"value": {"moderate": {"amount_minor_units": 350000, "term_days": 30}}},
    )
    assert changed.status_code == 200
    offer = client.get("/api/billing/catalogue", headers=auth).json()
    moderate = next(o for o in offer["options"] if o["tier"] == "moderate")
    assert moderate["amountMinorUnits"] == 350000
    assert moderate["termDays"] == 30


def test_a_checkout_charges_the_configured_price(client, admin_auth, auth):
    client.put(
        "/api/admin/commercial/catalogue",
        headers=admin_auth,
        json={"value": {"expert": {"amount_minor_units": 999900}}},
    )
    order = client.post("/api/billing/checkout", headers=auth, json={"tier": "expert"}).json()
    assert order["amountMinorUnits"] == 999900


def test_basic_can_never_be_priced(client, admin_auth):
    refused = client.put(
        "/api/admin/commercial/catalogue",
        headers=admin_auth,
        json={"value": {"basic": {"amount_minor_units": 100}}},
    )
    assert refused.status_code == 422
    assert "never sold" in refused.json()["detail"]


def test_a_nonsensical_price_is_refused(client, admin_auth):
    for bad in ({"amount_minor_units": -5}, {"amount_minor_units": 49.9}, {"term_days": 0}):
        refused = client.put(
            "/api/admin/commercial/catalogue", headers=admin_auth, json={"value": {"moderate": bad}}
        )
        assert refused.status_code == 422, bad


def test_run_allowance_is_admin_configurable_and_enforced(
    client, admin_auth, auth, fixture_dataset
):
    client.put(
        "/api/admin/commercial/allowance",
        headers=admin_auth,
        json={"value": {"basic": {"runs_per_module_per_week": 1}}},
    )
    matrix = client.get("/api/entitlements/matrix", headers=auth).json()
    assert matrix["allowance"]["runsPerModulePerWeek"] == 1

    body = {"dataset_id": fixture_dataset.id, "track": "core", "week": 3}
    assert client.post("/api/runs", headers=auth, json=body).status_code == 201
    second = client.post("/api/runs", headers=auth, json=body)
    assert second.status_code == 429
    assert second.json()["detail"]["error"] == "run_allowance_exhausted"


def test_basic_must_keep_one_run_and_one_what_if(client, admin_auth):
    """The commercial safeguard: promised learning is delivered at Basic."""
    for bad in ({"runs_per_module_per_week": 0}, {"perturbations_per_run": 0}):
        refused = client.put(
            "/api/admin/commercial/allowance", headers=admin_auth, json={"value": {"basic": bad}}
        )
        assert refused.status_code == 422, bad


def test_an_upgrade_can_never_take_something_away(client, admin_auth):
    refused = client.put(
        "/api/admin/commercial/allowance",
        headers=admin_auth,
        json={"value": {"moderate": {"runs_per_module_per_week": 1}, "basic": {"runs_per_module_per_week": 2}}},
    )
    assert refused.status_code == 422
    assert "take runs away" in refused.json()["detail"]


def test_commercial_keys_cannot_be_written_around_the_validation(client, admin_auth):
    refused = client.put(
        "/api/admin/settings",
        headers=admin_auth,
        json={"key": "commercial.catalogue", "value": {"basic": {"amount_minor_units": 1}}},
    )
    assert refused.status_code == 422


# ------------------------------------------------------------ issue reports --
def test_a_learner_can_report_an_issue_and_admin_can_resolve_it(client, auth, admin_auth):
    created = client.post(
        "/api/issues",
        headers=auth,
        json={"category": "scientific", "screen": "/runs/x", "message": "The QC step looks wrong to me."},
    )
    assert created.status_code == 201
    issue_id = created.json()["id"]
    assert client.get("/api/issues", headers=auth).json()[0]["id"] == issue_id

    queue = client.get("/api/admin/issues?status=open", headers=admin_auth).json()
    assert queue[0]["id"] == issue_id and queue[0]["email"] == "learner@example.com"

    resolved = client.patch(
        f"/api/admin/issues/{issue_id}",
        headers=admin_auth,
        json={"status": "resolved", "admin_note": "Threshold documented in the Knowledge Bank."},
    ).json()
    assert resolved["status"] == "resolved" and resolved["resolvedAt"]


def test_an_issue_cannot_be_attached_to_someone_elses_run(
    client, auth, db_session, moderate_user, fixture_dataset
):
    theirs = Run(
        user_id=moderate_user.id, dataset_id=fixture_dataset.id, track=AnalysisTrack.CORE,
        access_tier=AccessTier.MODERATE, pipeline_version="core-1.0.0", status=RunStatus.COMPLETED,
    )
    db_session.add(theirs)
    db_session.commit()
    refused = client.post(
        "/api/issues",
        headers=auth,
        json={"category": "technical", "message": "Something is wrong here.", "run_id": theirs.id},
    )
    assert refused.status_code == 404


def test_learners_cannot_read_the_admin_issue_queue(client, auth):
    assert client.get("/api/admin/issues", headers=auth).status_code == 403


# ------------------------------------------------------- week unlock (17) --
def test_admin_opens_the_next_week_for_a_cohort(client, admin_auth, auth, learner, db_session):
    assert client.get("/api/auth/me", headers=auth).json()["currentWeek"] == 1
    moved = client.post(
        "/api/admin/cohorts/week", headers=admin_auth, json={"cohort": "", "week": 3}
    ).json()
    assert moved["learnersMoved"] >= 1
    assert client.get("/api/auth/me", headers=auth).json()["currentWeek"] == 3
    home = client.get("/api/program/home", headers=auth).json()
    unlocked = [w["week"] for w in home["weeks"] if w["status"] == "open"]
    assert unlocked == [1, 2, 3]


def test_a_week_outside_the_programme_is_refused(client, admin_auth):
    assert client.post(
        "/api/admin/cohorts/week", headers=admin_auth, json={"cohort": "", "week": 9}
    ).status_code == 422


# -------------------------------------------------- run stores report (11) --
def test_a_run_records_the_report_generated_from_it(client, auth, db_session, learner, fixture_dataset):
    run = Run(
        user_id=learner.id, dataset_id=fixture_dataset.id, track=AnalysisTrack.CORE,
        access_tier=AccessTier.BASIC, pipeline_version="core-1.0.0", status=RunStatus.COMPLETED,
        outputs={"cluster": {"n_clusters": 3}},
    )
    db_session.add(run)
    db_session.commit()
    report = client.post(
        "/api/reports", headers=auth, json={"run_id": run.id, "export_format": "pdf_summary"}
    ).json()
    db_session.refresh(run)
    assert run.report_id == report["id"]


# ------------------------------------------------- completion + usage (14) --
def test_admin_sees_completion_status_and_dataset_load(client, admin_auth, learner):
    rows = client.get("/api/admin/completion", headers=admin_auth).json()
    mine = next(r for r in rows if r["email"] == "learner@example.com")
    assert mine["currentWeek"] == 1 and mine["capstoneSubmitted"] is False
    usage = client.get("/api/admin/usage", headers=admin_auth).json()
    assert "datasetLoad" in usage and "exportsByFormat" in usage
