"""The only door into the lab: a NanoSchool launch, verified by this server.

The hub is stubbed with an httpx transport rather than reached over the network,
so these tests pin what this side does with every answer the hub can give —
including the two that are easy to conflate, "no" and "no reply".
"""

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core import hub
from app.models import User
from app.settings import Settings, settings

LAUNCH = "launch-token-from-the-dashboard"


def _authorized(
    user_id: str = "hub-user-1",
    email: str = "learner@nanoschool.example",
    name: str = "A Learner",
    role: str = "USER",
    is_reviewer: bool = False,
    session_token: str = "hub-session-token",
) -> dict:
    return {
        "authorized": True,
        "user": {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "isReviewer": is_reviewer,
        },
        "lab": {"id": "lab-1", "slug": "omicslab", "name": "OmicsLab Pro"},
        "sessionToken": session_token,
        "sessionExpiresAt": "2026-09-13T00:00:00.000Z",
    }


@pytest.fixture()
def hub_stub(monkeypatch):
    """Replaces the hub with a handler the test controls.

    Returns a setter, so a test can change the hub's answer between launches.
    """
    state: dict = {"handler": lambda request: httpx.Response(200, json=_authorized())}
    state["requests"] = []

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(hub, "_client", lambda: httpx.Client(transport=transport))
    return state


def _launch(client, hub_stub=None, token: str = LAUNCH):
    return client.post(
        "/api/auth/lab-session",
        json={"token": token, "domainUrl": "https://omicslab.live-labs.org"},
    )


def _me(client, response):
    token = response.json()["access_token"]
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()


# ------------------------------------------------------------ a good launch --
def test_a_launch_opens_a_session_for_the_account_the_hub_named(client, hub_stub):
    response = _launch(client, hub_stub)
    assert response.status_code == 200
    body = response.json()

    assert body["identity"]["userId"] == "hub-user-1"
    assert body["identity"]["email"] == "learner@nanoschool.example"
    assert body["identity"]["labSlug"] == "omicslab"
    #: Relayed for the browser's own calls to NanoSchool — feedback, the
    #: reviewer agreement, the review form.
    assert body["hubSessionToken"] == "hub-session-token"

    me = _me(client, response)
    assert me["email"] == "learner@nanoschool.example"
    assert me["fullName"] == "A Learner"
    assert me["authSource"] == "nanoschool"


def test_the_hub_is_asked_with_the_launch_token_and_this_labs_identity(client, hub_stub):
    _launch(client, hub_stub)
    request = hub_stub["requests"][-1]
    assert str(request.url) == settings.hub_authorize_url
    import json

    sent = json.loads(request.content)
    assert sent["token"] == LAUNCH
    assert sent["domainUrl"] == "https://omicslab.live-labs.org"
    #: Sent as well as the domain, so a catalogue row whose domainUrl differs
    #: from this deployment's address still resolves to the right lab.
    assert sent["labSlug"] == settings.lab_slug


def test_the_launch_token_is_never_handed_back_to_the_browser(client, hub_stub):
    """It is spent. Echoing it would put a credential back in the page for no
    reason, and the hub refuses a second use of it anyway."""
    assert LAUNCH not in _launch(client, hub_stub).text


def test_each_learner_gets_their_own_account(client, hub_stub, db_session):
    first = _me(client, _launch(client, hub_stub))
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(user_id="hub-user-2", email="second@nanoschool.example")
    )
    second = _me(client, _launch(client, hub_stub))
    assert first["id"] != second["id"]


def test_the_same_person_returns_to_the_same_account(client, hub_stub, db_session):
    """Matching is by the hub's user id, which is what holds still. Work done in
    week one has to still be there in week eight, from another browser."""
    first = _me(client, _launch(client, hub_stub))
    second = _me(client, _launch(client, hub_stub))
    assert first["id"] == second["id"]
    assert len(db_session.scalars(select(User)).all()) == 1


def test_a_changed_email_does_not_strand_the_learners_work(client, hub_stub):
    first = _me(client, _launch(client, hub_stub))
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(email="new-address@nanoschool.example", name="A Learner Renamed")
    )
    second = _me(client, _launch(client, hub_stub))
    assert second["id"] == first["id"]
    #: The hub owns these details, so the lab takes its word for them.
    assert second["email"] == "new-address@nanoschool.example"
    assert second["fullName"] == "A Learner Renamed"


def test_an_account_with_no_email_on_the_hub_still_opens_the_lab(client, hub_stub):
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(email="", name="")
    )
    me = _me(client, _launch(client, hub_stub))
    assert me["id"]
    assert me["email"].endswith("@hub.invalid")


# --------------------------------------------------------------- admin, SME --
def test_a_hub_admin_arrives_as_a_lab_admin(client, hub_stub):
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(role="SUPER_ADMIN")
    )
    assert _me(client, _launch(client, hub_stub))["isAdmin"] is True


def test_an_ordinary_learner_is_not_a_lab_admin(client, hub_stub):
    assert _me(client, _launch(client, hub_stub))["isAdmin"] is False


def test_an_administrator_seeded_by_email_is_adopted_on_first_launch(
    client, hub_stub, db_session
):
    """How an operator with no hub admin role is appointed: scripts/seed.py
    writes the row, and the launch finds it by address."""
    db_session.add(
        User(email="learner@nanoschool.example", full_name="Seeded", is_admin=True)
    )
    db_session.commit()

    me = _me(client, _launch(client, hub_stub))
    assert me["isAdmin"] is True
    #: Adopted, not duplicated — otherwise the appointment would sit on an
    #: empty row while the person worked in a second account.
    rows = db_session.scalars(select(User)).all()
    assert len(rows) == 1
    assert rows[0].hub_user_id == "hub-user-1"


def test_launching_the_lab_does_not_demote_a_seeded_administrator(client, hub_stub, db_session):
    db_session.add(
        User(email="learner@nanoschool.example", full_name="Seeded", is_admin=True)
    )
    db_session.commit()
    _launch(client, hub_stub)
    #: The hub says USER; the flag was set deliberately in this database, and
    #: taking it away is also a deliberate act rather than a side effect.
    assert _me(client, _launch(client, hub_stub))["isAdmin"] is True


def test_the_reviewer_flag_follows_the_hub_including_being_taken_away(client, hub_stub):
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(is_reviewer=True)
    )
    assert _me(client, _launch(client, hub_stub))["isReviewer"] is True

    hub_stub["handler"] = lambda request: httpx.Response(
        200, json=_authorized(is_reviewer=False)
    )
    assert _me(client, _launch(client, hub_stub))["isReviewer"] is False


# ------------------------------------------------------------------ refusal --
def test_a_refusal_is_403_carrying_the_hubs_own_reason(client, hub_stub, db_session):
    hub_stub["handler"] = lambda request: httpx.Response(
        403,
        json={
            "authorized": False,
            "status": "FAILED_UNAUTHORIZED",
            "message": "You are not authorized to access this lab.",
        },
    )
    response = _launch(client, hub_stub)
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "launch_refused"
    assert detail["message"] == "You are not authorized to access this lab."
    #: So the client can offer the way out without hard-coding the hub.
    assert detail["loginUrl"] == settings.hub_login_url
    assert db_session.scalars(select(User)).all() == []


def test_an_authorised_launch_with_no_account_behind_it_is_refused(
    client, hub_stub, db_session
):
    """Every run and report here belongs to an account. A nameless session
    would pool one person's work with the next."""
    hub_stub["handler"] = lambda request: httpx.Response(
        200, json={"authorized": True, "lab": {"id": "lab-1", "slug": "omicslab"}}
    )
    response = _launch(client, hub_stub)
    assert response.status_code == 403
    assert "account" in response.json()["detail"]["message"]
    assert db_session.scalars(select(User)).all() == []


def test_a_missing_token_is_rejected_before_the_hub_is_asked(client, hub_stub):
    assert client.post("/api/auth/lab-session", json={}).status_code == 422
    assert hub_stub["requests"] == []


# -------------------------------------------------------------- no reply at all --
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("connect-error", id="connection refused"),
        pytest.param("timeout", id="timeout"),
        pytest.param("server-error", id="hub 500"),
        pytest.param("not-json", id="html from a proxy"),
    ],
)
def test_a_hub_that_does_not_answer_is_503_not_a_refusal(client, hub_stub, answer):
    """Sending someone back to sign in cannot fix a hub that is not answering,
    and telling them their account was refused would be a lie about where the
    fault is."""

    def handler(request: httpx.Request) -> httpx.Response:
        if answer == "connect-error":
            raise httpx.ConnectError("connection refused", request=request)
        if answer == "timeout":
            raise httpx.ReadTimeout("too slow", request=request)
        if answer == "server-error":
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, text="<html>maintenance</html>")

    hub_stub["handler"] = handler
    response = _launch(client, hub_stub)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "hub_unreachable"


def test_lab_sessions_are_rate_limited(client, hub_stub, monkeypatch):
    """The limit is what stands between a stolen launch link and an attempt to
    guess one."""
    from app.core import ratelimit

    monkeypatch.setattr(settings, "lab_session_rate_limit", "3/300")
    ratelimit.reset()
    for _ in range(3):
        _launch(client, hub_stub)
    blocked = _launch(client, hub_stub)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


# ------------------------------------------------- nothing else opens a session --
@pytest.mark.parametrize(
    "path", ["/api/auth/login", "/api/auth/register", "/api/auth/guest", "/api/auth/password"]
)
def test_there_is_no_credential_endpoint_left(client, path):
    """The screens were removed; these are the endpoints behind them. If any
    still issued a token, the launch gate would be decoration."""
    response = client.post(path, json={"email": "a@b.example", "password": "whatever-1"})
    assert response.status_code in (404, 405)
    assert "access_token" not in response.text


def test_a_token_from_the_old_credential_less_session_no_longer_works(client, learner):
    """The open-access endpoint is gone, but tokens it issued were sitting in
    browsers with hours left on them. Removing the way in for everyone except
    the people already inside would not be removing it."""
    import jwt
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    old_style = jwt.encode(
        {"sub": learner.id, "iat": now, "nbf": now, "exp": now + timedelta(hours=12)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_style}"})
    assert response.status_code == 401


def test_the_development_session_is_absent_unless_asked_for(client):
    assert client.post("/api/auth/dev-session").status_code == 404


def test_the_development_session_opens_the_lab_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_lab_session", True)
    response = client.post("/api/auth/dev-session")
    assert response.status_code == 200
    body = response.json()
    assert body["development"] is True
    #: And names nobody. A plausible identity nobody verified is how a lab ends
    #: up filing an expert's undertaking against an account that does not exist,
    #: so the governance screens get null here and say they cannot proceed.
    assert body["identity"] is None
    assert body["hubSessionToken"] is None
    me = _me(client, response)
    #: Never presented as a NanoSchool session, because nobody vouched for it.
    assert me["authSource"] == "local"


def test_an_email_two_accounts_claim_does_not_break_a_launch(client, hub_stub, db_session):
    """The hub's addresses are not this table's to arrange. Two accounts can end
    up pointing at one — and a routine launch must not become a 500 over it."""
    db_session.add(User(email="learner@nanoschool.example", hub_user_id="hub-someone-else"))
    db_session.commit()

    me = _me(client, _launch(client, hub_stub))
    #: A new row, identified by its hub id, keeping a stale address rather than
    #: colliding on the unique column.
    assert me["id"]
    assert me["email"] != "learner@nanoschool.example"
    rows = {u.hub_user_id: u.email for u in db_session.scalars(select(User)).all()}
    assert rows["hub-someone-else"] == "learner@nanoschool.example"


def test_production_refuses_to_start_with_the_development_session_enabled():
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            cors_origins="https://lab.example.com",
            dev_lab_session=True,
            _env_file=None,
        )
    assert "OMICSLAB_DEV_LAB_SESSION" in str(exc.value)


def test_production_refuses_a_plaintext_hub_address():
    """Launch tokens travel to it."""
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            cors_origins="https://lab.example.com",
            hub_base_url="http://live-labs.org",
            _env_file=None,
        )
    assert "OMICSLAB_HUB_BASE_URL" in str(exc.value)


# ----------------------------------------------------- the tier on arrival --
def test_an_account_holds_basic_by_default(client, hub_stub, monkeypatch):
    """The value a public deployment must have. Asserted against the default in
    code as well as a live launch, because the running settings read whatever
    .env this machine carries."""
    assert Settings(_env_file=None).granted_tier == "basic"

    monkeypatch.setattr(settings, "granted_tier", "basic")
    assert _me(client, _launch(client, hub_stub))["accessTier"] == "basic"


def test_the_granted_tier_can_be_raised_for_evaluation(client, hub_stub, monkeypatch):
    monkeypatch.setattr(settings, "granted_tier", "expert")
    response = _launch(client, hub_stub)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["accessTier"] == "expert"

    #: A grant, not a bypass: the entitlement machinery is what opened them.
    matrix = client.get("/api/entitlements/matrix", headers=headers).json()
    assert [f for f in matrix["features"] if f["available"] and not f["unlocked"]] == []


def test_lowering_the_granted_tier_takes_the_paid_features_back(client, hub_stub, monkeypatch):
    def tier_now() -> str:
        return _me(client, _launch(client, hub_stub))["accessTier"]

    monkeypatch.setattr(settings, "granted_tier", "expert")
    assert tier_now() == "expert"
    monkeypatch.setattr(settings, "granted_tier", "moderate")
    assert tier_now() == "moderate"
    monkeypatch.setattr(settings, "granted_tier", "basic")
    assert tier_now() == "basic"


def test_a_purchased_tier_is_not_touched_by_the_switch(db_session, expert_user, monkeypatch):
    """A real grant belongs to the account, not to this setting."""
    from app.constants import AccessTier
    from app.core.access import effective_tier

    monkeypatch.setattr(settings, "granted_tier", "basic")
    assert effective_tier(db_session, expert_user.id) is AccessTier.EXPERT


def test_an_unknown_granted_tier_is_refused_at_startup():
    with pytest.raises(ValidationError) as exc:
        Settings(granted_tier="unlimited", _env_file=None)
    assert "OMICSLAB_GRANTED_TIER" in str(exc.value)


def test_the_compose_file_still_reads_the_settings_old_name():
    """This setting was OMICSLAB_OPEN_ACCESS_TIER when the lab ran on a shared
    credential-less session, and that is the name sitting in a deployed
    deployment's environment. Losing it would silently drop an evaluation
    deployment back to Basic, which looks like the paid features breaking."""
    import pathlib

    compose = (
        pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml"
    ).read_text()
    assert "OMICSLAB_GRANTED_TIER" in compose
    assert "OMICSLAB_OPEN_ACCESS_TIER" in compose
