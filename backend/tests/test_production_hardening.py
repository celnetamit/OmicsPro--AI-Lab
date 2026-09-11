"""The deployment surface: configuration refusal, headers, limits, recovery.

These are the behaviours a launch depends on and that no scientific test would
notice if they regressed.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.constants import RunStatus
from app.core import jobs, ratelimit
from app.core.security import (
    PasswordPolicyError,
    decode_access_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.models import Run
from app.settings import Settings


# ------------------------------------------------------------ configuration --
def test_production_refuses_the_development_signing_key():
    """A secret that ships in the repository is not a secret."""
    with pytest.raises(ValidationError) as exc:
        Settings(environment="production", jwt_secret="dev-only-change-me", _env_file=None)
    assert "OMICSLAB_JWT_SECRET" in str(exc.value)


def test_production_refuses_a_short_signing_key():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="tooshort", _env_file=None)


def test_production_refuses_wildcard_cors_with_credentials():
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            cors_origins="*",
            _env_file=None,
        )
    assert "CORS" in str(exc.value)


def test_production_starts_with_a_real_configuration():
    settings = Settings(
        environment="production",
        jwt_secret="x" * 40,
        cors_origins="https://lab.example.com, https://alt.example.com",
        _env_file=None,
    )
    assert settings.is_production
    assert settings.cors_origin_list == ["https://lab.example.com", "https://alt.example.com"]


# ------------------------------------------------------------------ health --
def test_health_reports_liveness_without_touching_the_database(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "release" in body and "activePhase" in body


def test_readiness_checks_the_database(client):
    body = client.get("/api/health/ready").json()
    assert body["database"] == "ok"
    assert body["runsInFlight"] == 0


def test_every_response_carries_the_security_headers_and_a_request_id(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Request-ID"]


def test_errors_carry_the_request_id_so_a_learner_can_quote_it(client):
    body = client.get("/api/runs/does-not-exist").json()
    assert body.get("requestId") or body["detail"].get("requestId")


# ------------------------------------------------------------- credentials --
@pytest.mark.parametrize(
    "weak",
    ["short", "password", "1234567890123", "abcdefghijkl", "PASSWORD"],
)
def test_the_password_policy_rejects_weak_choices(weak):
    with pytest.raises(PasswordPolicyError):
        validate_password(weak)


def test_the_password_policy_accepts_a_long_mixed_password():
    validate_password("orbital-sequencer-7")


def test_a_password_cannot_be_the_email_address():
    with pytest.raises(PasswordPolicyError):
        validate_password("learner@example.com", email="learner@example.com")


def test_registration_refuses_a_weak_password(client):
    response = client.post(
        "/api/auth/register", json={"email": "new@example.com", "password": "short"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "weak_password"


def test_registration_accepts_a_strong_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "strong@example.com", "password": "orbital-sequencer-7"},
    )
    assert response.status_code == 201
    assert decode_access_token(response.json()["access_token"])


def test_a_password_beyond_bcrypts_limit_is_refused_not_truncated():
    """bcrypt hashes only the first 72 bytes; a silent truncation would let a
    different, shorter password authenticate."""
    with pytest.raises(PasswordPolicyError):
        hash_password("a1" * 40)


def test_a_corrupt_stored_hash_is_a_failed_login_not_a_crash():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_login_is_rate_limited(client, learner, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "login_rate_limit", "3/300")
    ratelimit.reset()
    for _ in range(3):
        client.post("/api/auth/login", json={"email": learner.email, "password": "wrong-pass-1"})
    blocked = client.post(
        "/api/auth/login", json={"email": learner.email, "password": "secret-pass"}
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


def test_login_does_not_reveal_whether_an_account_exists(client, learner):
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "secret-pass"}
    )
    wrong = client.post(
        "/api/auth/login", json={"email": learner.email, "password": "wrong-pass-1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_a_learner_can_change_their_password(client, auth, learner):
    response = client.post(
        "/api/auth/password",
        json={"current_password": "secret-pass", "new_password": "orbital-sequencer-7"},
        headers=auth,
    )
    assert response.status_code == 204
    assert client.post(
        "/api/auth/login", json={"email": learner.email, "password": "orbital-sequencer-7"}
    ).status_code == 200
    assert client.post(
        "/api/auth/login", json={"email": learner.email, "password": "secret-pass"}
    ).status_code == 401


def test_changing_a_password_requires_the_current_one(client, auth):
    response = client.post(
        "/api/auth/password",
        json={"current_password": "not-my-password", "new_password": "orbital-sequencer-7"},
        headers=auth,
    )
    assert response.status_code == 403


def test_an_expired_token_is_rejected(client, learner, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
    from app.core.security import create_access_token

    stale = create_access_token(learner.id)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale}"})
    assert response.status_code == 401


# ------------------------------------------------------------- run recovery --
def test_an_interrupted_run_is_closed_out_on_restart(db_session, learner, fixture_dataset, monkeypatch):
    """A run marked RUNNING with no worker behind it would otherwise show as in
    progress forever."""
    orphan = Run(
        user_id=learner.id,
        dataset_id=fixture_dataset.id,
        track=fixture_dataset.track,
        access_tier="basic",
        pipeline_version="core-1.0.0",
        status=RunStatus.RUNNING,
        started_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(orphan)
    db_session.commit()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert jobs.reap_orphaned_runs() == 1
    db_session.refresh(orphan)
    assert orphan.status == RunStatus.FAILED
    assert "restarted" in orphan.error_message
    assert orphan.finished_at is not None


def test_a_completed_run_is_never_reaped(db_session, learner, fixture_dataset, monkeypatch):
    done = Run(
        user_id=learner.id,
        dataset_id=fixture_dataset.id,
        track=fixture_dataset.track,
        access_tier="basic",
        pipeline_version="core-1.0.0",
        status=RunStatus.COMPLETED,
        started_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(done)
    db_session.commit()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert jobs.reap_orphaned_runs() == 0
    db_session.refresh(done)
    assert done.status == RunStatus.COMPLETED


def test_an_executor_crash_records_a_failed_run_rather_than_losing_it(
    db_session, learner, fixture_dataset, monkeypatch
):
    run = Run(
        user_id=learner.id,
        dataset_id=fixture_dataset.id,
        track=fixture_dataset.track,
        access_tier="basic",
        pipeline_version="core-1.0.0",
        status=RunStatus.QUEUED,
    )
    db_session.add(run)
    db_session.commit()

    def _explode(*_args, **_kwargs):
        raise RuntimeError("the executor itself broke")

    monkeypatch.setattr(jobs.runner, "execute", _explode)
    jobs._run_one(db_session, run, object(), None)

    db_session.refresh(run)
    assert run.status == RunStatus.FAILED
    assert "nothing you submitted was lost" in run.error_message.lower()


# ------------------------------------------------------------ rate limiter --
def test_the_rate_limiter_is_per_client_and_expires():
    ratelimit.reset()
    assert [ratelimit.check("b", "10.0.0.1", "2/60")[0] for _ in range(3)] == [True, True, False]
    assert ratelimit.check("b", "10.0.0.2", "2/60")[0] is True
    #: A different bucket for the same client is independent.
    assert ratelimit.check("other", "10.0.0.1", "2/60")[0] is True
    assert ratelimit.check("b", "10.0.0.1", "2/60")[1] > 0


# ------------------------------------------------------------- open access --
def test_the_lab_opens_without_credentials(client, monkeypatch):
    """Open access: a visitor gets a real, enrolled session.

    The tier is pinned here rather than assumed: it is configurable, and this
    machine's own .env raises it for evaluation. What this test defends is that
    the session exists and belongs to someone, not which tier it holds — that
    is covered by the open-access tier tests below.
    """
    from app.settings import settings

    monkeypatch.setattr(settings, "open_access_tier", "basic")
    response = client.post("/api/auth/guest")
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["accessTier"] == "basic"
    assert me["openAccess"] is True
    #: Still a real owner, because runs, interpretations and reports belong to one.
    assert me["id"]


def test_open_access_reuses_one_shared_account(client):
    first = client.post("/api/auth/guest").json()["access_token"]
    second = client.post("/api/auth/guest").json()["access_token"]
    ids = {
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"}).json()["id"]
        for t in (first, second)
    }
    assert len(ids) == 1


def test_the_open_access_account_cannot_be_logged_into(client):
    """Its password is random and never issued, so the shared session is only
    reachable through the guest endpoint.

    Its address is on a ``.local`` domain, which the email validator refuses
    outright, so an attempt is rejected before it even reaches the password
    check. Either way the invariant is the same: no attempt yields a token.
    """
    from app.settings import settings

    client.post("/api/auth/guest")
    for attempt in ("guest", "password", "change-me-now", settings.guest_email):
        response = client.post(
            "/api/auth/login", json={"email": settings.guest_email, "password": attempt}
        )
        assert response.status_code in (401, 422)
        assert "access_token" not in response.json()


def test_open_access_can_be_turned_off_to_restore_the_sign_in_screen(client, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "open_access", False)
    assert client.post("/api/auth/guest").status_code == 404


# ----------------------------------------------- open-access tier for testing --
def test_the_open_session_holds_basic_by_default(client, monkeypatch):
    """The value a public deployment must have.

    Asserted against the default in code rather than the running settings
    object, which reads whatever .env the operator has on the machine — here,
    an evaluation deployment set to expert.
    """
    from app.settings import Settings, settings

    assert Settings(_env_file=None).open_access_tier == "basic"

    monkeypatch.setattr(settings, "open_access_tier", "basic")
    token = client.post("/api/auth/guest").json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["accessTier"] == "basic"


def test_the_open_session_can_be_raised_for_evaluation(client, monkeypatch):
    """An evaluation deployment opens the paid features on the shared account."""
    from app.settings import settings

    monkeypatch.setattr(settings, "open_access_tier", "expert")
    token = client.post("/api/auth/guest").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["accessTier"] == "expert"

    #: It is a grant, not a bypass: the entitlement machinery is what opened it.
    matrix = client.get("/api/entitlements/matrix", headers=headers).json()
    locked = [f for f in matrix["features"] if f["available"] and not f["unlocked"]]
    assert locked == []


def test_raising_the_open_tier_does_not_touch_registered_learners(client, monkeypatch):
    """A real account's tier comes from its own entitlements, never this switch."""
    from app.settings import settings

    monkeypatch.setattr(settings, "open_access_tier", "expert")
    registered = client.post(
        "/api/auth/register",
        json={"email": "real-learner@example.com", "password": "orbital-sequencer-7"},
    ).json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {registered}"}).json()
    assert me["accessTier"] == "basic"


def test_an_unknown_open_access_tier_is_refused_at_startup():
    import pytest
    from pydantic import ValidationError

    from app.settings import Settings

    with pytest.raises(ValidationError) as exc:
        Settings(open_access_tier="unlimited", _env_file=None)
    assert "OMICSLAB_OPEN_ACCESS_TIER" in str(exc.value)
