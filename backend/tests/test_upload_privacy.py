"""Spec 6: an uploaded dataset is private to the learner who uploaded it.

The upload response promises the data is "never shared with other users".
These tests hold every route that reaches a dataset to that promise.
"""

from app.constants import AccessTier, AnalysisTrack
from app.core.security import create_access_token
from app.models import Dataset, Enrollment, Entitlement, User


def _second_expert(db_session, client):
    user = User(email="second-expert@example.com", hub_user_id="hub-second-expert")
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(user_id=user.id, program_code="flagship-8w"))
    db_session.add(Entitlement(user_id=user.id, tier=AccessTier.BASIC))
    db_session.add(Entitlement(user_id=user.id, tier=AccessTier.EXPERT, source="purchase"))
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _upload(db_session, owner) -> Dataset:
    dataset = Dataset(
        slug="upload-private-test",
        name="A learner's own upload",
        track=AnalysisTrack.CORE,
        kind="upload",
        source="Uploaded by the learner",
        accession="own-data",
        license="The learner's own",
        storage_path=f"uploads/{owner.id}/not-materialised",
        owner_id=owner.id,
        validation_status="validated",
        supported_modules=["core_guided"],
        limitations=[],
    )
    db_session.add(dataset)
    db_session.commit()
    return dataset


def test_an_upload_is_listed_only_for_its_owner(client, db_session, expert_user, expert_auth):
    dataset = _upload(db_session, expert_user)
    other = _second_expert(db_session, client)
    assert dataset.id in [d["id"] for d in client.get("/api/datasets", headers=expert_auth).json()]
    assert dataset.id not in [d["id"] for d in client.get("/api/datasets", headers=other).json()]


def test_another_learner_cannot_inspect_explain_or_run_an_upload(client, db_session, expert_user):
    dataset = _upload(db_session, expert_user)
    other = _second_expert(db_session, client)
    # Absent rather than forbidden, so the upload's existence is not disclosed.
    assert client.get(f"/api/datasets/{dataset.id}", headers=other).status_code == 404
    assert client.get(f"/api/datasets/{dataset.id}/brief", headers=other).status_code == 404
    run = client.post("/api/runs", headers=other, json={"dataset_id": dataset.id, "track": "core"})
    assert run.status_code == 404


def test_the_owner_still_reaches_their_upload(client, db_session, expert_user, expert_auth):
    dataset = _upload(db_session, expert_user)
    assert client.get(f"/api/datasets/{dataset.id}", headers=expert_auth).status_code == 200
    assert client.get(f"/api/datasets/{dataset.id}/brief", headers=expert_auth).status_code == 200
