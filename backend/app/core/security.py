"""This lab's session token.

There is nothing else in here, and the absence is the design: OmicsLab accepts
no passwords. NanoSchool authenticates the person (see ``app/core/hub.py``) and
this issues a short-lived bearer token that says "the hub vouched for user X at
time T", which is what every protected endpoint then checks.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.settings import settings

#: Bumped when a token issued under the old rules must stop working.
#:
#: Version 1 tokens were handed out by the open-access endpoint, which opened
#: the lab to anyone with no credential and no NanoSchool account. Removing that
#: endpoint stops new ones being issued; refusing this version is what stops the
#: ones already sitting in people's browsers, which would otherwise keep working
#: until they expired — a sign-in screen removed everywhere except for whoever
#: had already been let in.
TOKEN_VERSION = 2


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "ver": TOKEN_VERSION,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("ver") != TOKEN_VERSION:
        #: Not an error worth explaining to the client: the front end treats any
        #: rejected token as "the session has ended" and offers a relaunch,
        #: which is exactly the right move here.
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
