"""The deployment surface: configuration refusal, headers, limits, recovery.

These are the behaviours a launch depends on and that no scientific test would
notice if they regressed.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.constants import RunStatus
from app.core import jobs, ratelimit
from app.core.security import create_access_token
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
# There are none. This lab issues no passwords and accepts none: a session
# exists only because NanoSchool verified a launch, which tests/test_lab_auth.py
# covers end to end. What remains here is the session token's own lifetime.
def test_an_expired_token_is_rejected(client, learner, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
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


# The open-access session, the shared credential-less account and the tier it
# carried now belong to tests/test_lab_auth.py, where the tier is a property of
# each NanoSchool account rather than of one account everybody shared.
