"""Verification of a NanoSchool launch, done by this server.

OmicsLab holds no credentials of its own. A learner arrives from the NanoSchool
dashboard with a short-lived launch token in the address bar, and that token is
the only thing that opens the lab.

The verification happens **here**, not in the browser, and that is the whole
point of this module. The other Live Labs are client-only apps, so their guard
asks the hub directly and then trusts its own answer — there is no server behind
them to fool. OmicsLab has a server that stores runs, interpretations and
reports against an account, so if the browser were the one to decide who it is,
anyone could claim to be anyone by posting a name to the API. Instead the
browser hands the launch token to this API, this API asks the hub, and the
identity comes back over a channel the browser cannot sit in the middle of.

Asking once also matters. The hub replay-checks launch tokens: the first
success is recorded, and the same token presented more than ten seconds later
is refused as an already-used launch link. A design where the browser verified
and then the server verified again would spend that budget twice for one launch
and break on a slow connection. So the browser never calls authorize-lab; it
calls us, and we call the hub.

Three outcomes, and they are deliberately not collapsed into two:

  * authorised  — the hub named the account and the lab;
  * refused     — the hub answered, and the answer was no. Sending the learner
                  back to the dashboard to launch again is the right move;
  * unreachable — no answer at all. Bouncing them to a login they can already
                  reach would be a lie about where the fault is, so this one
                  offers a retry instead.
"""

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.settings import settings

#: Hub roles that carry the lab's own admin console. SUPER_ADMIN is the hub's
#: platform owner (its `hasLabAccess` short-circuits on it); ADMIN is the
#: programme staff role. Everything else opens the lab as a learner.
HUB_ADMIN_ROLES = frozenset({"ADMIN", "SUPER_ADMIN"})


@dataclass(frozen=True)
class HubIdentity:
    """The account the hub vouched for. Every field comes from its response."""

    user_id: str
    email: Optional[str]
    name: Optional[str]
    #: The hub's role string: USER, ADMIN, SUPER_ADMIN, …
    role: str
    #: Whether the hub marks this account as an expert reviewer. A presentation
    #: hint: the hub re-reads it from its own database on every review call.
    is_reviewer: bool
    lab_id: Optional[str]
    lab_slug: Optional[str]

    @property
    def is_admin(self) -> bool:
        return self.role.upper() in HUB_ADMIN_ROLES


@dataclass(frozen=True)
class HubAuthorization:
    identity: HubIdentity
    #: The hub's own session credential, for the browser's later calls to
    #: NanoSchool (feedback, the reviewer agreement, the review form). This
    #: server does not use it; it relays it to the client that asked.
    session_token: Optional[str]
    session_expires_at: Optional[str]


class HubRefused(Exception):
    """The hub answered, and the answer was no."""

    def __init__(self, message: str, status: str = "") -> None:
        super().__init__(message)
        self.message = message
        #: The hub's own status code, e.g. FAILED_UNAUTHORIZED. Logged, not shown.
        self.status = status


class HubUnreachable(Exception):
    """No answer from the hub. Not a refusal, and must not be shown as one."""


def _client() -> httpx.Client:
    """The HTTP client used for the hub call. Replaced wholesale in tests."""
    return httpx.Client(timeout=settings.hub_timeout_seconds)


def _text(value: Any) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def authorize_launch(token: str, domain_url: Optional[str] = None) -> HubAuthorization:
    """Exchange a launch token for the verified account behind it.

    Raises ``HubRefused`` when the hub says no and ``HubUnreachable`` when it
    does not answer. A 5xx is treated as unreachable rather than as a refusal:
    a fault at the hub is not a statement about this learner.
    """
    payload = {
        "token": token,
        #: The hub resolves the lab by domain or by slug. Both are sent, so a
        #: deployment on a new domain still resolves while the catalogue row is
        #: being updated, and a catalogue row with a trailing-slash mismatch
        #: does not lock everyone out.
        "domainUrl": domain_url or settings.lab_public_url,
        "labSlug": settings.lab_slug,
    }

    try:
        with _client() as client:
            response = client.post(settings.hub_authorize_url, json=payload)
    except httpx.HTTPError as exc:
        raise HubUnreachable(str(exc)) from exc

    if response.status_code >= 500:
        raise HubUnreachable(f"NanoSchool answered {response.status_code}.")

    try:
        body = response.json()
    except ValueError as exc:
        #: HTML from a proxy, or an empty body. Either way nobody has answered
        #: the question that was asked.
        raise HubUnreachable("NanoSchool's reply was not JSON.") from exc

    if not isinstance(body, dict):
        raise HubUnreachable("NanoSchool's reply was not an object.")

    if body.get("authorized") is not True:
        raise HubRefused(
            _text(body.get("message"))
            or "NanoSchool did not authorise this launch.",
            status=_text(body.get("status")) or "",
        )

    user = body.get("user") if isinstance(body.get("user"), dict) else {}
    user_id = _text(user.get("id"))
    if not user_id:
        #: Authorised but unnameable. The client-only labs open anyway and scope
        #: their work to the browser. This lab cannot: every run, report and
        #: assessment belongs to an account, and pooling them under a shared
        #: nameless owner is the bug that produced one shared project history
        #: across an entire browser. Refuse, and say why.
        raise HubRefused(
            "NanoSchool authorised this launch but did not say which account it "
            "belongs to, and this lab stores your work against an account. "
            "Launch the lab again from the dashboard."
        )

    lab = body.get("lab") if isinstance(body.get("lab"), dict) else {}

    return HubAuthorization(
        identity=HubIdentity(
            user_id=user_id,
            email=(_text(user.get("email")) or "").lower() or None,
            name=_text(user.get("name")),
            role=(_text(user.get("role")) or "USER").upper(),
            is_reviewer=user.get("isReviewer") is True,
            lab_id=_text(lab.get("id")),
            lab_slug=_text(lab.get("slug")),
        ),
        session_token=_text(body.get("sessionToken")),
        session_expires_at=_text(body.get("sessionExpiresAt")),
    )
