import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Test-suite configuration, set before app.settings is imported.
import tempfile  # noqa: E402

#: Hermetic by construction. Without this the app's startup (which reaps
#: orphaned runs) queried the developer's own omicslab.db, and the settings read
#: whatever .env the machine carries — on this one, production mode and an
#: expert open-access tier. A suite whose result depends on a developer's local
#: files is not testing the code.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="omicslab-tests-")
os.environ["OMICSLAB_DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/app.db"
os.environ["OMICSLAB_ENVIRONMENT"] = "development"
os.environ["OMICSLAB_OPEN_ACCESS_TIER"] = "basic"
#: Runs complete before the response returns, so a test can assert on results.
os.environ.setdefault("OMICSLAB_RUN_EXECUTION_MODE", "inline")
#: The production work factor makes the suite spend minutes hashing passwords.
os.environ.setdefault("OMICSLAB_BCRYPT_ROUNDS", "4")
os.environ.setdefault("OMICSLAB_LOG_LEVEL", "WARNING")

from app.constants import AccessTier, AnalysisTrack  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Dataset, Enrollment, Entitlement, User  # noqa: E402
from app.core.security import hash_password  # noqa: E402


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Each test starts with a clean limiter; otherwise the login fixtures of
    one module exhaust the window for the next."""
    from app.core import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def learner(db_session):
    user = User(email="learner@example.com", password_hash=hash_password("secret-pass"))
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(user_id=user.id, program_code="flagship-8w"))
    db_session.add(Entitlement(user_id=user.id, tier=AccessTier.BASIC))
    db_session.commit()
    return user


@pytest.fixture()
def auth(client, learner):
    token = client.post(
        "/api/auth/login", json={"email": learner.email, "password": "secret-pass"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fixture_dataset(db_session):
    dataset = Dataset(
        slug="synthetic-core-fixture",
        name="Synthetic development fixture (not teaching content)",
        track=AnalysisTrack.CORE,
        kind="guided",
        source="scripts/seed.py",
        accession="SYNTHETIC-FIXTURE-001",
        license="Synthetic data",
        storage_path="fixtures/synthetic-core",
        validation_status="validated",
        limitations=["Synthetic data with no biological meaning."],
    )
    db_session.add(dataset)
    db_session.commit()
    return dataset


def _tiered_user(db_session, email: str, tier: AccessTier) -> User:
    user = User(email=email, password_hash=hash_password("secret-pass"))
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(user_id=user.id, program_code="flagship-8w"))
    db_session.add(Entitlement(user_id=user.id, tier=AccessTier.BASIC))
    if tier is not AccessTier.BASIC:
        db_session.add(Entitlement(user_id=user.id, tier=tier, source="purchase"))
    db_session.commit()
    return user


def _token(client, user) -> dict:
    token = client.post(
        "/api/auth/login", json={"email": user.email, "password": "secret-pass"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def moderate_user(db_session):
    return _tiered_user(db_session, "moderate@example.com", AccessTier.MODERATE)


@pytest.fixture()
def moderate_auth(client, moderate_user):
    return _token(client, moderate_user)


@pytest.fixture()
def expert_user(db_session):
    return _tiered_user(db_session, "expert@example.com", AccessTier.EXPERT)


@pytest.fixture()
def expert_auth(client, expert_user):
    return _token(client, expert_user)


@pytest.fixture()
def admin_auth(client, db_session):
    user = User(
        email="admin@example.com", password_hash=hash_password("secret-pass"), is_admin=True
    )
    db_session.add(user)
    db_session.commit()
    return _token(client, user)


@pytest.fixture()
def spatial_dataset(db_session, tmp_path, monkeypatch):
    """A synthetic single-section package on a regular capture array."""
    import json

    import numpy as np

    from app.settings import settings

    directory = tmp_path / "fixtures"
    directory.mkdir(exist_ok=True)
    rng = np.random.default_rng(11)
    rows, cols, n_genes = 14, 14, 200
    genes = [f"GENE{i:03d}" for i in range(n_genes)]
    obs, blocks = [], []
    for r in range(rows):
        for c in range(0, cols * 2, 2):
            column = c + (r % 2)
            zone = 0 if (r + column / 2) < rows else 1
            profile = rng.negative_binomial(6, 0.3, size=n_genes)
            profile[:40] = profile[:40] * (4 if zone else 1)
            blocks.append(profile)
            obs.append(
                {
                    "spot_id": f"s{r}_{column}",
                    "array_row": r,
                    "array_col": column,
                    "x": float(column * 50),
                    "y": float(r * 87),
                    "sample_id": "section1",
                    "section_id": "section1",
                    "specimen_id": "specimen1",
                    "condition": "tumour" if zone else "adjacent",
                }
            )
    np.savez_compressed(directory / "spatial.npz", matrix=np.vstack(blocks))
    (directory / "spatial.meta.json").write_text(json.dumps({"obs": obs, "var": genes}))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    dataset = Dataset(
        slug="spatial-fixture",
        name="Synthetic spatial fixture (not teaching content)",
        track=AnalysisTrack.ADVANCED,
        kind="guided",
        source="test fixture",
        accession="SYNTHETIC-FIXTURE-002",
        license="Synthetic data",
        storage_path="fixtures/spatial",
        validation_status="validated",
        limitations=["Synthetic data with no biological meaning."],
    )
    db_session.add(dataset)
    db_session.commit()
    return dataset
