"""Application settings. Scientific defaults live in the parameter registry.

Everything here is environment-driven so one image runs in every deployment.
Production refuses to start on a development secret: a signing key that ships
in the repository is not a secret, and a JWT signed with it is forgeable by
anyone who can read the source.
"""

from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

#: The value shipped in the repository. Usable in development, refused in
#: production by the guard in ``_check_production_secrets``.
DEV_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    app_name: str = "OmicsLab Pro"
    #: "development" | "staging" | "production". Only "production" is strict.
    environment: str = "development"
    #: Stamped onto /api/health and the footer so a deployment can be identified.
    release: str = "dev"

    database_url: str = "sqlite:///./omicslab.db"
    #: Postgres connection pool. Ignored for SQLite.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    #: Signs this lab's own session token, which is issued only after the hub
    #: has verified a launch. It authenticates nobody by itself.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12

    # ---------------------------------------------------------------- #
    # NanoSchool (live-labs.org), which owns the accounts
    # ---------------------------------------------------------------- #
    #: The hub. Override for a staging platform; trailing slashes tolerated.
    hub_base_url: str = "https://live-labs.org"
    #: This lab's slug in the hub's catalogue, sent so the hub can resolve the
    #: lab even if its `domainUrl` row and this deployment's domain differ.
    lab_slug: str = "omicslab"
    #: Where this lab is reachable. Sent as the launch's `domainUrl` when the
    #: client does not supply one, and used in the relaunch link.
    lab_public_url: str = "https://omicslab.live-labs.org"
    #: A hub that has not answered by now is treated as unreachable. Long
    #: enough for a cold start, short enough not to look hung.
    hub_timeout_seconds: float = 12.0
    #: Local development and smoke tests only: allows POST /api/auth/dev-session
    #: to open a lab session with no hub at all. Refused in production, and off
    #: unless deliberately set — with it on, anyone who can reach the API can
    #: open the lab.
    dev_lab_session: bool = False

    #: Tier every NanoSchool account starts with in this lab. "basic" is what a
    #: real learner gets and is the only correct value for a public deployment.
    #: Raise it to "moderate" or "expert" on an evaluation deployment to open
    #: every paid feature without buying or granting one — the entitlement
    #: machinery is unchanged, the account simply holds a higher grant, and
    #: every server-side check runs exactly as it always does.
    #:
    #: Named OMICSLAB_OPEN_ACCESS_TIER while the lab ran on a shared
    #: credential-less session. docker-compose.yml still reads that variable and
    #: passes it here, so a deployment configured under the old name keeps
    #: working; the mapping lives there rather than in an alias on this field,
    #: because an environment variable that quietly outranks an explicitly
    #: passed value is a trap (it silently won over `Settings(granted_tier=…)`).
    granted_tier: str = "basic"

    data_dir: str = "./data"
    cors_origins: str = "http://localhost:5173"
    #: Host header allow-list. "*" disables the check (correct behind a proxy
    #: that already validates Host, which is how Coolify fronts this service).
    trusted_hosts: str = "*"
    #: Sent as Strict-Transport-Security when the environment is production.
    hsts_max_age_seconds: int = 60 * 60 * 24 * 365

    #: Sliding-window limits, "attempts/seconds", applied per client IP. The
    #: lab-session limit is what stands between a stolen launch link and an
    #: attempt to brute-force one; it is generous enough that a learner
    #: reloading a broken tab a few times never meets it.
    lab_session_rate_limit: str = "20/300"
    #: Blanket per-IP ceiling for the whole API. Generous: the workspace is chatty.
    global_rate_limit: str = "600/60"

    #: Pipeline execution. "background" returns the queued run immediately and
    #: executes on the worker pool; "inline" blocks the request until the run
    #: finishes, which is what the test suite asserts against.
    run_execution_mode: str = "background"
    run_worker_threads: int = 2
    #: A run still RUNNING after this long is reaped as failed on next boot.
    run_stale_after_minutes: int = 180

    log_level: str = "INFO"
    #: JSON lines when true, human-readable when false.
    log_json: bool = True

    max_upload_bytes: int = 512 * 1024 * 1024

    model_config = {"env_prefix": "OMICSLAB_", "env_file": ".env", "extra": "ignore"}

    @field_validator("environment")
    @classmethod
    def _normalise_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("granted_tier")
    @classmethod
    def _known_tier(cls, value: str) -> str:
        from app.constants import AccessTier

        tier = value.strip().lower()
        if tier not in {t.value for t in AccessTier}:
            raise ValueError(
                "OMICSLAB_GRANTED_TIER must be one of: "
                + ", ".join(t.value for t in AccessTier)
            )
        return tier

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def hub_authorize_url(self) -> str:
        return f"{self.hub_base_url.rstrip('/')}/api/auth/authorize-lab"

    @property
    def hub_login_url(self) -> str:
        """Where a visitor with no launch token is sent to sign in."""
        return f"{self.hub_base_url.rstrip('/')}/login"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> List[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if not self.is_production:
            return self
        problems = []
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append(
                "OMICSLAB_JWT_SECRET must be set to a random value of at least 32 "
                "characters in production (generate one with: openssl rand -hex 32)"
            )
        if self.dev_lab_session:
            problems.append(
                "OMICSLAB_DEV_LAB_SESSION must not be set in production: it opens "
                "a lab session to anyone who can reach the API, with no launch "
                "token and no NanoSchool account behind it"
            )
        if not self.hub_base_url.lower().startswith("https://"):
            problems.append(
                "OMICSLAB_HUB_BASE_URL must be an https:// address in production: "
                "launch tokens and account details travel to it"
            )
        if "*" in self.cors_origin_list:
            problems.append(
                "OMICSLAB_CORS_ORIGINS cannot be '*' in production: the API sends "
                "credentials, and a wildcard origin with credentials is both "
                "unsafe and rejected by browsers"
            )
        if problems:
            raise ValueError(
                "Refusing to start in production with an unsafe configuration:\n  - "
                + "\n  - ".join(problems)
            )
        return self


settings = Settings()
