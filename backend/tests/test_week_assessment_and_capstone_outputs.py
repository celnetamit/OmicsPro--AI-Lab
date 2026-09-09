"""Week assessment and the capstone outputs spec 13 asks for.

The rule these tests defend: a score is only ever reported for work that was
actually recorded. A component with nothing behind it is *not assessable*, not
zero — a zero would claim the learner reasoned badly when the truth is that
they have not reached that part of the week.
"""

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.content.assessment import questions_for
from app.models import Interpretation, Run


def _completed_run(db_session, user, dataset, week: int) -> Run:
    """A completed run without needing the single-cell worker in the test env."""
    run = Run(
        user_id=user.id,
        dataset_id=dataset.id,
        track=AnalysisTrack.CORE,
        week=week,
        access_tier=AccessTier.EXPERT,
        pipeline_version="core-1.0.0",
        method_versions={"pipeline": "core-1.0.0", "clustering": "Leiden 0.10.2"},
        parameters={"sc.cluster.resolution": 1.0},
        outputs={
            "cluster": {"n_clusters": 6, "cluster_sizes": [10, 20, 30, 5, 8, 9]},
            "de": {"n_significant": 12, "table": [{"gene": "GENE001", "padj": 0.01}]},
        },
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    db_session.commit()
    return run


def _answers(week: int, correct: bool = True) -> dict:
    questions = questions_for(week)
    if correct:
        return {q["id"]: q["answer"] for q in questions}
    return {
        q["id"]: next(o for o in q["options"] if o != q["answer"]) for q in questions
    }


# ------------------------------------------------------------- week assessment --
def test_the_week_assessment_offers_concept_questions_without_their_answers(client, auth):
    body = client.get("/api/program/assessment?week=3", headers=auth).json()
    assert body["assessmentId"] == "week-3"
    assert body["questions"]
    for question in body["questions"]:
        assert "answer" not in question and "explanation" not in question
        assert question["options"]


def test_concept_answers_are_marked_objectively(client, auth):
    right = client.post(
        "/api/program/assessment", headers=auth, json={"week": 3, "responses": _answers(3)}
    ).json()
    concepts = next(c for c in right["components"] if c["key"] == "concepts")
    assert concepts["score"] == 1.0

    wrong = client.post(
        "/api/program/assessment",
        headers=auth,
        json={"week": 3, "responses": _answers(3, correct=False)},
    ).json()
    concepts = next(c for c in wrong["components"] if c["key"] == "concepts")
    assert concepts["score"] == 0.0
    assert wrong["recommendedTopics"]


def test_a_component_with_no_recorded_work_is_not_scored_zero(client, auth):
    """The distinction the whole design rests on."""
    body = client.post(
        "/api/program/assessment", headers=auth, json={"week": 3, "responses": _answers(3)}
    ).json()
    measured = {c["key"]: c for c in body["components"] if c["key"] != "concepts"}
    for component in measured.values():
        assert component["assessable"] is False
        assert component["score"] is None
        assert component["notes"]
    assert set(body["pendingComponents"]) == {c["label"] for c in measured.values()}
    #: The overall figure is the mean of what could be assessed, not of zeros.
    assert body["score"] == 1.0


def test_the_measured_components_read_the_learners_own_record(
    client, auth, learner, fixture_dataset, db_session
):
    run = _completed_run(db_session, learner, fixture_dataset, week=3)
    client.post(
        f"/api/runs/{run.id}/interpretation",
        headers=auth,
        json={
            "step": "clustering",
            "observation": "Few cells removed",
            "statistical_evidence": "counts before and after",
            "biological_interpretation": "population intact",
            "hypothesis": "proceed",
        },
    )
    body = client.post(
        "/api/program/assessment", headers=auth, json={"week": 3, "responses": _answers(3)}
    ).json()
    interpretation = next(c for c in body["components"] if c["key"] == "interpretation")
    assert interpretation["assessable"] is True
    assert interpretation["total"] == 1


def test_the_week_assessment_is_persisted(client, auth, learner, db_session):
    from app.models import AssessmentResult

    client.post(
        "/api/program/assessment", headers=auth, json={"week": 2, "responses": _answers(2)}
    )
    saved = (
        db_session.query(AssessmentResult)
        .filter(AssessmentResult.assessment_id == "week-2")
        .all()
    )
    assert saved and saved[-1].week == 2

    again = client.get("/api/program/assessment?week=2", headers=auth).json()
    assert again["previousScore"] is not None


# ------------------------------------------------------------ capstone outputs --
def test_the_memo_is_assembled_from_the_record_and_states_its_length(
    client, expert_auth, expert_user, fixture_dataset, db_session
):
    run = _completed_run(db_session, expert_user, fixture_dataset, week=4)
    client.post(
        f"/api/runs/{run.id}/interpretation",
        headers=expert_auth,
        json={
            "step": "clustering",
            "observation": "o",
            "statistical_evidence": "s",
            "biological_interpretation": "The treated cells shift composition.",
            "hypothesis": "h",
        },
    )
    client.put(
        "/api/capstone",
        headers=expert_auth,
        json={
            "title": "Steroid response",
            "research_question": "Do airway cells respond?",
            "run_ids": [run.id],
            "limitations": ["Synthetic teaching data."],
            "future_work": "Repeat in donors.",
        },
    )
    memo = client.get("/api/capstone/memo", headers=expert_auth).json()

    #: The claim is the learner's own, carried with the label it was given.
    claims = [f["claim"] for f in memo["sections"]["findings"]]
    assert "The treated cells shift composition." in claims
    #: Length is measured, not promised.
    assert memo["estimatedWords"] > 0
    assert memo["withinTwoPages"] == (memo["estimatedPages"] <= 2)
    assert memo["sections"]["limitations"]
    assert not memo["missing"]


def test_the_memo_says_what_is_still_missing(client, expert_auth, expert_user):
    memo = client.get("/api/capstone/memo", headers=expert_auth).json()
    assert "the research question" in memo["missing"]
    assert memo["sections"]["findings"] == []


def test_submitting_records_a_defence_score_built_from_the_record(
    client, expert_auth, expert_user, fixture_dataset, db_session
):
    run = _completed_run(db_session, expert_user, fixture_dataset, week=8)
    client.post(
        f"/api/runs/{run.id}/interpretation",
        headers=expert_auth,
        json={
            "step": "clustering",
            "observation": "o",
            "statistical_evidence": "s",
            "biological_interpretation": "b",
            "hypothesis": "h",
        },
    )
    client.put(
        "/api/capstone",
        headers=expert_auth,
        json={
            "title": "Capstone",
            "research_question": "Q?",
            "run_ids": [run.id],
            "figures": [{"figureId": "cluster_sizes", "runId": run.id}],
            "limitations": ["One synthetic dataset."],
        },
    )
    #: Adjudicate every Copilot output so the audit component can be scored.
    for row in client.get(
        f"/api/copilot/interactions?run_id={run.id}", headers=expert_auth
    ).json():
        client.post(
            "/api/copilot/audit",
            headers=expert_auth,
            json={"interaction_id": row["id"], "action": "accept", "final_interpretation": "ok"},
        )

    submitted = client.post("/api/capstone/submit", headers=expert_auth)
    assert submitted.status_code == 200, submitted.json()
    body = submitted.json()
    assert body["defenceScore"] is not None
    parts = {p["key"]: p for p in body["defence"]["parts"]}
    assert parts["interpretation"]["score"] == 1.0
    assert parts["limits"]["score"] == 1.0
    #: It measures defensibility, never whether the biology is right.
    assert "not a judgement" in body["defence"]["note"]

    #: The score is stored, so it stays true to what was defended.
    reread = client.get("/api/capstone", headers=expert_auth).json()
    assert reread["defenceScore"] == body["defenceScore"]
