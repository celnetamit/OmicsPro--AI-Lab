"""Definition of Done: tiers separate from tracks, Basic auto-granted, gates
enforced server-side, expiry does not delete history (spec 13)."""

from datetime import datetime, timedelta

import pytest

from app.constants import ACTIVE_PHASE, AccessTier, AnalysisTrack
from app.core import entitlements as ent
from app.core.access import effective_tier, ensure_basic_auto_grant
from app.models import Entitlement, Report, Run


def test_tier_and_track_vocabularies_do_not_overlap():
    tiers = {t.value for t in AccessTier}
    tracks = {t.value for t in AnalysisTrack}
    assert tiers.isdisjoint(tracks)


def test_every_teaching_core_feature_is_basic():
    """Paid tiers sell depth, never the promised learning outcome (spec 2)."""
    for feature in ent.FEATURES.values():
        if feature.teaching_core:
            assert feature.min_tier is AccessTier.BASIC, feature.key


def test_locked_features_carry_upgrade_copy():
    """Locked features stay visible with an explanation, never hidden (spec 2)."""
    for feature in ent.FEATURES.values():
        if feature.min_tier is not AccessTier.BASIC:
            assert feature.locked_explanation.strip(), feature.key


def test_matrix_reports_locked_rows_to_the_client():
    rows = ent.matrix_for(AccessTier.BASIC, ACTIVE_PHASE)
    locked = [r for r in rows if not r["unlocked"]]
    assert locked, "Basic must still see the paid features as locked"
    assert all(r["lockedExplanation"] for r in locked)


def test_assert_feature_blocks_and_allows():
    ent.assert_feature(AccessTier.BASIC, "run_guided_pipeline")
    with pytest.raises(ent.EntitlementError):
        ent.assert_feature(AccessTier.BASIC, "dataset_upload")
    ent.assert_feature(AccessTier.EXPERT, "dataset_upload")


def test_unknown_feature_cannot_be_checked_silently():
    with pytest.raises(KeyError):
        ent.has_feature(AccessTier.BASIC, "not_a_declared_feature")


def test_basic_auto_grant_is_idempotent(db_session, learner):
    first = ensure_basic_auto_grant(db_session, learner.id)
    second = ensure_basic_auto_grant(db_session, learner.id)
    assert first.id == second.id
    assert effective_tier(db_session, learner.id) is AccessTier.BASIC


def test_a_new_nanoschool_account_auto_grants_basic(db_session, client):
    """Basic comes with enrollment and is never sold (spec 2). Enrollment is
    now the launch itself: the hub says this person may open the lab."""
    from app.core.hub import HubIdentity
    from app.core.lab_session import provision
    from app.core.security import create_access_token

    user = provision(
        db_session,
        HubIdentity(
            user_id="hub-new-learner",
            email="new@example.com",
            name="New Learner",
            role="USER",
            is_reviewer=False,
            lab_id="lab-1",
            lab_slug="omicslab",
        ),
    )
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["accessTier"] == AccessTier.BASIC.value


def test_expiry_downgrades_access_but_keeps_reports(db_session, learner):
    past = datetime.utcnow() - timedelta(days=1)
    db_session.add(
        Entitlement(
            user_id=learner.id,
            tier=AccessTier.MODERATE,
            source="purchase",
            granted_at=past - timedelta(days=30),
            expires_at=past,
        )
    )
    run = Run(
        user_id=learner.id,
        dataset_id="d1",
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.MODERATE,
        pipeline_version="core-1.0.0",
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        Report(
            user_id=learner.id,
            run_id=run.id,
            generated_tier=AccessTier.MODERATE,
            export_format="pdf_full",
            content={},
        )
    )
    db_session.commit()

    assert effective_tier(db_session, learner.id) is AccessTier.BASIC
    assert db_session.query(Report).filter(Report.user_id == learner.id).count() == 1


def test_backend_rejects_locked_endpoint_regardless_of_client(client, auth):
    """The gate is server-side: a Basic token cannot reach a paid endpoint."""
    response = client.post(
        "/api/runs",
        headers=auth,
        json={
            "dataset_id": "any",
            "track": "core",
            "parameters": {"sc.cluster.resolution": 1.2},
        },
    )
    assert response.status_code in (403, 404)
    if response.status_code == 403:
        assert response.json()["detail"]["feature"] == "independent_rerun"
