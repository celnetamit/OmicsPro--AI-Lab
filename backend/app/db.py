"""Engine and session factory.

SQLite is the development and test store; Postgres is the deployment store.
The only difference the application sees is the pool configuration below.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.settings import settings

_is_sqlite = settings.database_url.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(
        settings.database_url, connect_args={"check_same_thread": False}, future=True
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        """Write-ahead logging and enforced foreign keys.

        Without WAL a background run holding a write transaction blocks every
        reader, which is exactly the shape of this application's traffic.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

else:
    engine = create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,  # a connection killed by the server is replaced, not raised
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables for the development store.

    Deployments run Alembic instead (``alembic upgrade head``); this stays for
    SQLite development and the test suite, where a migration run is noise.
    """
    Base.metadata.create_all(engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
