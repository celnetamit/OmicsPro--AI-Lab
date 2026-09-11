"""Application settings. Scientific defaults live in the parameter registry.

Everything here is environment-driven so one image runs in every deployment.
Production refuses to start on a development secret: a signing key that ships
in the repository is not a secret, and a JWT signed with it is forgeable by
anyone who can read the source.
"""

from typing import List

from pydantic import Field, field_validator, model_validator
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

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12
    #: Work factor for password hashing. Lowered only by the test suite.
    bcrypt_rounds: int = 12
    #: Minimum length enforced at registration and password change.
    min_password_length: int = 10

    #: Open access: the Live Lab opens straight into the workspace on a shared
    #: demo session, with no sign-in and no sign-out control. The whole
    #: credential path stays implemented and tested underneath — set this to
    #: false to put the sign-in screen back in front of the app.
    open_access: bool = True
    #: The account an open-access visitor is signed in as.
    guest_email: str = "guest@omicslab.local"
    guest_name: str = "Lab visitor"
    #: Tier the open-access session carries. "basic" is what a real learner
    #: gets and is the only correct value for a public deployment. Raise it to
    #: "moderate" or "expert" on an evaluation or development deployment to
    #: open every paid feature without having to buy or grant one — the
    #: entitlement machinery is unchanged, the shared account simply holds a
    #: higher grant, and every server-side check runs exactly as it always does.
    open_access_tier: str = "basic"

    data_dir: str = "./data"
    cors_origins: str = "http://localhost:5173"
    #: Host header allow-list. "*" disables the check (correct behind a proxy
    #: that already validates Host, which is how Coolify fronts this service).
    trusted_hosts: str = "*"
    #: Sent as Strict-Transport-Security when the environment is production.
    hsts_max_age_seconds: int = 60 * 60 * 24 * 365

    #: Sliding-window limits, "attempts/seconds", applied per client IP.
    login_rate_limit: str = "10/300"
    register_rate_limit: str = "5/3600"
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

    @field_validator("open_access_tier")
    @classmethod
    def _known_tier(cls, value: str) -> str:
        from app.constants import AccessTier

        tier = value.strip().lower()
        if tier not in {t.value for t in AccessTier}:
            raise ValueError(
                "OMICSLAB_OPEN_ACCESS_TIER must be one of: "
                + ", ".join(t.value for t in AccessTier)
            )
        return tier

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
