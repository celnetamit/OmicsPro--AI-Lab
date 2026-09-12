"""Seed the database with the launch content.

Appoints an administrator by email, creates the guided dataset records with
their provenance, the runtime-editable settings, and a clearly-labelled
synthetic fixture so the full Phase 1 flow can be exercised before the real
teaching data is ingested.

Guided datasets are seeded as ``pending_data_ingest``: they are not selectable
until scripts/fetch_guided_data.py has downloaded and validated the real files.
No placeholder results are ever written in their place.
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.constants import AccessTier, AnalysisTrack  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AdminSetting, Dataset, Enrollment, Entitlement, User  # noqa: E402
from app.settings import settings  # noqa: E402

GUIDED_DATASETS = [
    {
        "slug": "airway-dexamethasone",
        "name": "Airway smooth muscle, glucocorticoid treated",
        "track": AnalysisTrack.FOUNDATION,
        "kind": "guided",
        "source": "NCBI Gene Expression Omnibus",
        "accession": "GSE52778",
        "citation": "Himes et al., PLoS ONE 2014, doi:10.1371/journal.pone.0099625",
        "license": "Public, GEO terms of use",
        "description": (
            "Analysis-ready count matrix and sample sheet for four donors, each "
            "with a treated and an untreated culture."
        ),
        "storage_path": "guided/airway-dexamethasone",
        "file_format": "npz",
        "supported_modules": ["foundation_guided"],
        "limitations": [
            "Cultured cells, not tissue: the response may differ in vivo.",
            "Four donors is adequate for a paired design and small for anything else.",
        ],
    },
    {
        "slug": "pbmc-interferon-beta",
        "name": "Peripheral blood mononuclear cells, interferon stimulated",
        "track": AnalysisTrack.CORE,
        "kind": "guided",
        "source": "NCBI Gene Expression Omnibus",
        "accession": "GSE96583",
        "citation": "Kang et al., Nature Biotechnology 2018, doi:10.1038/nbt.4042",
        "license": "Public, GEO terms of use",
        "description": (
            "Multiplexed droplet single-cell data from several donors, each with a "
            "stimulated and an unstimulated aliquot."
        ),
        "storage_path": "guided/pbmc-interferon-beta",
        "file_format": "npz",
        "supported_modules": ["core_qc", "core_clustering", "differential_expression"],
        "limitations": [
            "Dissociated blood cells: fragile populations are under-represented.",
            "Donor is the replication unit; cell counts do not increase replication.",
        ],
    },
]

GUIDED_DATASETS.append(
    {
        "slug": "visium-breast-cancer",
        "name": "Visium spatial gene expression, human breast tissue",
        "track": AnalysisTrack.ADVANCED,
        "kind": "guided",
        "source": "10x Genomics public datasets",
        "accession": "10x-visium-human-breast-cancer-v1",
        "citation": "10x Genomics, Visium Spatial Gene Expression demonstration data",
        "license": "Public, 10x Genomics dataset terms of use",
        "description": (
            "A single Visium section with expression, spot coordinates and "
            "capture-array positions."
        ),
        "storage_path": "guided/visium-breast-cancer",
        "file_format": "npz",
        "supported_modules": ["advanced_guided"],
        "limitations": [
            "One section from one specimen: every region comparison drawn from it "
            "is descriptive and hypothesis-generating, not population-level "
            "inference.",
            "Each spot covers several cells, so any cell type estimate per spot "
            "is compositional and probabilistic, never a single-cell identity.",
        ],
    }
)

TRIAL_DATASETS = [
    {
        "slug": "pbmc-3k-trial",
        "name": "Peripheral blood mononuclear cells, unstimulated",
        "track": AnalysisTrack.CORE,
        "kind": "trial",
        "source": "10x Genomics public datasets",
        "accession": "10x-pbmc-3k-v1",
        "citation": "10x Genomics, single cell gene expression demonstration data",
        "license": "Public, 10x Genomics dataset terms of use",
        "description": (
            "A single-sample blood dataset for practising quality control, "
            "clustering and annotation independently."
        ),
        "storage_path": "trial/pbmc-3k",
        "file_format": "npz",
        "supported_modules": ["core_qc", "core_clustering"],
        "limitations": [
            "One sample and one condition: it supports practice with clustering "
            "and annotation, and supports no condition comparison at all.",
        ],
    },
    {
        "slug": "airway-trial",
        "name": "Bulk RNA-seq practice matrix, treated and untreated",
        "track": AnalysisTrack.FOUNDATION,
        "kind": "trial",
        "source": "NCBI Gene Expression Omnibus",
        "accession": "GSE52778",
        "citation": "Himes et al., PLoS ONE 2014, doi:10.1371/journal.pone.0099625",
        "license": "Public, GEO terms of use",
        "description": (
            "A held-out subset of the guided bulk dataset, for practising the "
            "statistical design and contrast independently."
        ),
        "storage_path": "trial/airway-subset",
        "file_format": "npz",
        "supported_modules": ["foundation_guided"],
        "limitations": [
            "A subset of the guided dataset, so it is practice rather than an "
            "independent replication of it.",
        ],
    },
]

SETTINGS = [
    ("upload.max_bytes", {"basic": 0, "moderate": 0, "expert": 2 * 1024 * 1024 * 1024}),
    ("retention.uploaded_dataset_days", {"days": 180}),
    ("retention.report_days", {"days": None, "note": "Reports are retained indefinitely."}),
    ("upload.deletion_behaviour", {"mode": "hard_delete_on_expiry", "gracePeriodDays": 14}),
    (
        "governance.training_use",
        {
            "allowUserDataForModelTraining": False,
            "allowCrossUserSharing": False,
            "note": "Uploaded data is never reused for training or shared between users.",
        },
    ),
]


def make_fixture(directory: str) -> None:
    """Write a synthetic development fixture, labelled as such everywhere.

    This exists so the pipeline, entitlement and Copilot flows can be exercised
    end to end without the real teaching data. It is not teaching content and
    its numbers carry no biological meaning.
    """
    rng = np.random.default_rng(0)
    os.makedirs(directory, exist_ok=True)

    n_cells, n_genes = 400, 800
    genes = [f"GENE{i:04d}" for i in range(n_genes - 5)] + [
        f"MT-SYN{i}" for i in range(5)
    ]
    obs = []
    blocks = []
    for donor in range(4):
        condition = "stimulated" if donor % 2 else "control"
        cells = n_cells // 4
        base = rng.negative_binomial(5, 0.3, size=(cells, n_genes))
        if condition == "stimulated":
            base[:, :60] = base[:, :60] * 3
        blocks.append(base)
        obs.extend(
            {
                "cell_id": f"d{donor}_c{i}",
                "sample_id": f"donor{donor}",
                "donor": f"donor{donor}",
                "condition": condition,
                "batch": "batch1",
            }
            for i in range(cells)
        )
    matrix = np.vstack(blocks)

    np.savez_compressed(os.path.join(directory, "synthetic-core.npz"), matrix=matrix)
    with open(os.path.join(directory, "synthetic-core.meta.json"), "w") as handle:
        json.dump({"obs": obs, "var": genes}, handle)


def make_spatial_fixture(directory: str) -> None:
    """Synthetic spatial fixture on a regular capture array, labelled as such."""
    rng = np.random.default_rng(7)
    os.makedirs(directory, exist_ok=True)

    rows, cols = 24, 24
    n_genes = 400
    genes = [f"GENE{i:04d}" for i in range(n_genes - 4)] + [f"MT-SYN{i}" for i in range(4)]

    obs, blocks = [], []
    for r in range(rows):
        for c in range(cols):
            # Two spatially contiguous zones so domain detection has structure
            # to find; the values themselves carry no biological meaning.
            zone = 0 if (r + c) < (rows + cols) / 2 else 1
            profile = rng.negative_binomial(5, 0.3, size=n_genes)
            profile[:60] = profile[:60] * (4 if zone else 1)
            blocks.append(profile)
            obs.append(
                {
                    "spot_id": f"s{r}_{c}",
                    "array_row": r,
                    "array_col": c,
                    "x": float(c * 100 + (r % 2) * 50),
                    "y": float(r * 87),
                    "sample_id": "section1",
                    "section_id": "section1",
                    "specimen_id": "specimen1",
                    "condition": "tumour" if zone else "adjacent",
                }
            )

    np.savez_compressed(os.path.join(directory, "synthetic-spatial.npz"), matrix=np.vstack(blocks))
    with open(os.path.join(directory, "synthetic-spatial.meta.json"), "w") as handle:
        json.dump({"obs": obs, "var": genes}, handle)


def main() -> None:
    init_db()
    db = SessionLocal()

    # The administrator is appointed by email, not by credential. This lab
    # accepts no passwords: NanoSchool authenticates everyone, and a session
    # exists only because it verified a launch. So the row seeded here is an
    # empty account waiting for a person — when whoever holds this address
    # launches the lab from their dashboard, that launch is matched to this row
    # (app/core/lab_session.py) and they arrive as an administrator.
    #
    # Two ways to appoint one, and either is enough:
    #   * set OMICSLAB_ADMIN_EMAIL here, for someone whose hub role is an
    #     ordinary learner but who runs ingestion and dataset sign-off;
    #   * give them the ADMIN or SUPER_ADMIN role on the hub, which grants this
    #     lab's admin console with nothing to seed at all.
    admin_email = os.environ.get("OMICSLAB_ADMIN_EMAIL", "").strip().lower()
    if not admin_email:
        print(
            "No OMICSLAB_ADMIN_EMAIL set, so no administrator was seeded. "
            "A NanoSchool account with the ADMIN or SUPER_ADMIN role already "
            "opens the admin console; set this variable to appoint someone who "
            "does not have one."
        )
    elif not db.query(User).filter(User.email == admin_email).first():
        admin = User(
            email=admin_email,
            full_name="Platform administrator",
            is_admin=True,
        )
        db.add(admin)
        db.flush()
        db.add(Enrollment(user_id=admin.id, program_code="flagship-8w", cohort="staff"))
        db.add(Entitlement(user_id=admin.id, tier=AccessTier.EXPERT, source="admin_grant"))
        print(
            f"Appointed {admin_email} as administrator. It becomes a usable "
            "account when they launch the lab from their NanoSchool dashboard."
        )
    else:
        print(f"{admin_email} already exists; left unchanged.")

    for spec in GUIDED_DATASETS + TRIAL_DATASETS:
        if db.query(Dataset).filter(Dataset.slug == spec["slug"]).first():
            continue
        db.add(
            Dataset(
                **spec,
                validation_status="pending_data_ingest",
                validation_report={
                    "note": (
                        "Files not yet ingested. Run scripts/fetch_guided_data.py, "
                        "then set validation_status to 'validated' once the "
                        "ingestion validator passes."
                    )
                },
            )
        )
        print(f"Seeded guided dataset {spec['slug']} ({spec['accession']})")

    fixture_dir = os.path.join(settings.data_dir, "fixtures")
    make_fixture(fixture_dir)
    make_spatial_fixture(fixture_dir)
    if not db.query(Dataset).filter(Dataset.slug == "synthetic-core-fixture").first():
        db.add(
            Dataset(
                slug="synthetic-core-fixture",
                name="Synthetic development fixture (not teaching content)",
                track=AnalysisTrack.CORE,
                kind="guided",
                source="Generated locally by scripts/seed.py",
                accession="SYNTHETIC-FIXTURE-001",
                citation="Not a published dataset.",
                license="Synthetic data, no restrictions",
                description=(
                    "Randomly generated counts used to exercise the platform end "
                    "to end before real teaching data is ingested."
                ),
                storage_path="fixtures/synthetic-core",
                file_format="npz",
                validation_status="validated",
                supported_modules=["core_qc", "core_clustering", "differential_expression"],
                limitations=[
                    "Synthetic data. Every result computed from it is meaningless "
                    "biologically and must never be presented as a finding.",
                ],
            )
        )
        print("Seeded the synthetic development fixture")

    if not db.query(Dataset).filter(Dataset.slug == "synthetic-spatial-fixture").first():
        db.add(
            Dataset(
                slug="synthetic-spatial-fixture",
                name="Synthetic spatial fixture (not teaching content)",
                track=AnalysisTrack.ADVANCED,
                kind="guided",
                source="Generated locally by scripts/seed.py",
                accession="SYNTHETIC-FIXTURE-002",
                citation="Not a published dataset.",
                license="Synthetic data, no restrictions",
                description=(
                    "A randomly generated section on a regular capture array, "
                    "used to exercise the spatial workflow before real teaching "
                    "data is ingested."
                ),
                storage_path="fixtures/synthetic-spatial",
                file_format="npz",
                validation_status="validated",
                supported_modules=["advanced_guided"],
                limitations=[
                    "Synthetic data. Every result computed from it is meaningless "
                    "biologically and must never be presented as a finding.",
                    "One synthetic specimen, so region comparison is descriptive "
                    "only, exactly as it would be for a single real section.",
                ],
            )
        )
        print("Seeded the synthetic spatial fixture")

    for key, value in SETTINGS:
        if db.get(AdminSetting, key) is None:
            db.add(AdminSetting(key=key, value=value))

    db.commit()
    db.close()
    print("Seed complete.")


if __name__ == "__main__":
    main()
