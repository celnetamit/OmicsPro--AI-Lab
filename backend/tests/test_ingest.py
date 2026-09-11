"""Spec 6 and 10: every route into the platform reads files the same way.

The Expert upload and the operator's guided ingestion share one set of readers.
These tests hold them to the orientation each pipeline reads, to matching
metadata by identifier rather than by order, and to refusing anything that is
not raw counts.
"""

import gzip
import io
import os

import numpy as np
import pandas as pd
import pytest
from scipy import io as scipy_io
from scipy import sparse

from app.constants import AnalysisTrack
from app.governance import ingest
from app.governance.ingest import IngestError, Source
from app.governance.validation import validate_upload

BULK = "gene,S1,S2,S3,S4\n" + "\n".join(f"G{i},{i},{i + 1},{i + 2},{i + 3}" for i in range(5)) + "\n"
BULK_META = "sample_id,condition\nS1,a\nS2,a\nS3,b\nS4,b\n"


def _text(content: str, name: str) -> Source:
    return Source(name, data=content.encode())


def _tenx(n_genes=6, n_cells=8, antibody_rows=0):
    """A small 10x Matrix Market triple: features × barcodes, gzipped like Cell Ranger's."""
    rng = np.random.default_rng(0)
    dense = rng.integers(0, 6, size=(n_genes, n_cells))
    buffer = io.BytesIO()
    scipy_io.mmwrite(buffer, sparse.coo_matrix(dense))
    features = "\n".join(
        f"ENSG{i:04d}\tGENE{i}\t{'Antibody Capture' if i >= n_genes - antibody_rows else 'Gene Expression'}"
        for i in range(n_genes)
    )
    barcodes = "\n".join(f"AAAC{i:04d}-1" for i in range(n_cells))
    return (
        dense,
        Source("matrix.mtx.gz", data=gzip.compress(buffer.getvalue())),
        Source("features.tsv.gz", data=gzip.compress(features.encode())),
        _text(barcodes, "barcodes.tsv"),
    )


def _cell_table(n_cells=8) -> Source:
    rows = "\n".join(
        f"AAAC{i:04d}-1,donor{i % 4},{'stimulated' if i % 2 else 'control'}" for i in range(n_cells)
    )
    return _text("barcode,sample_id,condition\n" + rows + "\n", "cells.csv")


# ------------------------------------------------------------------ bulk --
def test_a_bulk_table_is_stored_genes_by_samples():
    out = ingest.ingest(AnalysisTrack.FOUNDATION, _text(BULK, "counts.csv"), _text(BULK_META, "meta.csv"))
    assert out.matrix.shape == (5, 4)
    assert out.var[0] == "G0"
    assert [row["sample_id"] for row in out.obs] == ["S1", "S2", "S3", "S4"]


def test_metadata_is_matched_by_identifier_not_by_order():
    shuffled = "sample_id,condition\nS3,b\nS1,a\nS4,b\nS2,a\n"
    out = ingest.ingest(AnalysisTrack.FOUNDATION, _text(BULK, "counts.csv"), _text(shuffled, "meta.csv"))
    assert [(r["sample_id"], r["condition"]) for r in out.obs] == [
        ("S1", "a"), ("S2", "a"), ("S3", "b"), ("S4", "b"),
    ]


def test_a_sample_without_metadata_is_refused():
    partial = "sample_id,condition\nS1,a\nS2,a\nS3,b\n"
    with pytest.raises(IngestError) as refused:
        ingest.ingest(AnalysisTrack.FOUNDATION, _text(BULK, "counts.csv"), _text(partial, "meta.csv"))
    assert refused.value.code == "metadata_mismatch"


def test_normalised_values_cannot_stand_in_for_counts():
    normalised = "gene,S1,S2,S3,S4\nG0,0.5,1.2,3.3,0.1\n"
    with pytest.raises(IngestError) as refused:
        ingest.ingest(AnalysisTrack.FOUNDATION, _text(normalised, "counts.csv"), _text(BULK_META, "meta.csv"))
    assert refused.value.code == "not_raw_counts"


# ----------------------------------------------------------- single cell --
def test_a_10x_matrix_is_stored_cells_by_genes_with_symbols():
    dense, mtx, features, barcodes = _tenx()
    out = ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), features=features, barcodes=barcodes)
    assert out.matrix.shape == (8, 6)
    np.testing.assert_array_equal(out.matrix, dense.T)
    assert out.var[:2] == ["GENE0", "GENE1"]
    assert out.obs[3]["cell_id"] == "AAAC0003-1"
    assert out.obs[3]["condition"] == "stimulated"


def test_only_gene_expression_features_are_kept():
    _, mtx, features, barcodes = _tenx(antibody_rows=2)
    out = ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), features=features, barcodes=barcodes)
    assert out.matrix.shape == (8, 4)
    assert any("Gene Expression" in note for note in out.notes)


def test_an_mtx_without_gene_names_is_refused():
    _, mtx, _, barcodes = _tenx()
    with pytest.raises(IngestError) as refused:
        ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), barcodes=barcodes)
    assert refused.value.code == "missing_features"


def test_an_h5ad_is_read_from_its_counts_layer(tmp_path):
    anndata = pytest.importorskip("anndata")
    counts = (np.arange(24).reshape(6, 4) % 5).astype(np.int64)
    adata = anndata.AnnData(
        X=np.log1p(counts).astype(np.float32),
        obs=pd.DataFrame(
            {"sample_id": ["d0", "d0", "d1", "d1", "d2", "d3"], "condition": ["c", "c", "s", "s", "c", "s"]},
            index=[f"cell{i}" for i in range(6)],
        ),
        var=pd.DataFrame({"gene_symbols": [f"GENE{i}" for i in range(4)]}, index=[f"ENSG{i}" for i in range(4)]),
    )
    adata.layers["counts"] = counts
    path = tmp_path / "cells.h5ad"
    adata.write_h5ad(path)

    out = ingest.ingest(AnalysisTrack.CORE, Source.from_path(str(path)))
    np.testing.assert_array_equal(out.matrix, counts)
    assert out.var[0] == "GENE0"
    assert out.obs[2] == {"sample_id": "d1", "condition": "s", "cell_id": "cell2"}
    assert any("'counts' layer" in note for note in out.notes)


def test_an_h5ad_without_raw_counts_is_refused(tmp_path):
    anndata = pytest.importorskip("anndata")
    adata = anndata.AnnData(X=np.log1p(np.ones((3, 2), dtype=np.float32)))
    path = tmp_path / "normalised.h5ad"
    adata.write_h5ad(path)
    with pytest.raises(IngestError) as refused:
        ingest.ingest(AnalysisTrack.CORE, Source.from_path(str(path)))
    assert refused.value.code == "not_raw_counts"


# --------------------------------------------------------------- spatial --
def test_a_visium_section_keeps_spots_under_tissue_with_coordinates():
    _, mtx, features, barcodes = _tenx()
    positions = "barcode,in_tissue,array_row,array_col,pxl_row_in_fullres,pxl_col_in_fullres\n" + "\n".join(
        f"AAAC{i:04d}-1,{0 if i == 7 else 1},{i // 4},{i % 4},{100 + i},{200 + i}" for i in range(8)
    )
    out = ingest.ingest(
        AnalysisTrack.ADVANCED, mtx,
        features=features, barcodes=barcodes, positions=_text(positions, "tissue_positions.csv"),
        defaults={"sample_id": "section1", "condition": "reference"},
    )
    assert out.matrix.shape == (7, 6)
    first = out.obs[0]
    assert (first["spot_id"], first["x"], first["y"]) == ("AAAC0000-1", 200.0, 100.0)
    assert (first["array_row"], first["array_col"]) == (0, 0)
    assert first["sample_id"] == "section1"
    assert any("under tissue" in note for note in out.notes)


def test_space_ranger_positions_without_a_header_are_read():
    placed = ingest.read_positions(_text("AAAC0000-1,1,0,0,10,20\nAAAC0001-1,0,0,1,11,21\n", "tissue_positions_list.csv"))
    assert placed["AAAC0000-1"] == {"in_tissue": 1, "array_row": 0, "array_col": 0, "x": 20.0, "y": 10.0}


# ------------------------------------------------------ size and records --
def test_a_subsample_is_seeded_and_recorded():
    _, mtx, features, barcodes = _tenx()
    first = ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), features=features, barcodes=barcodes, max_observations=5)
    second = ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), features=features, barcodes=barcodes, max_observations=5)
    assert first.obs == second.obs and len(first.obs) == 5
    assert any("seeded subsample of 5 of 8 cells" in note for note in first.notes)


def test_an_object_too_large_for_memory_is_refused():
    _, mtx, features, barcodes = _tenx()
    with pytest.raises(IngestError) as refused:
        ingest.ingest(AnalysisTrack.CORE, mtx, _cell_table(), features=features, barcodes=barcodes, max_values=10)
    assert refused.value.code == "too_large_for_dense_object"


@pytest.mark.parametrize(
    "filename, accepted",
    [("matrix.mtx.gz", True), ("reads.fastq.gz", False), ("archive.gz", False)],
)
def test_a_compressed_file_is_judged_by_what_it_holds(filename, accepted):
    result = validate_upload(filename=filename, size_bytes=10, track=AnalysisTrack.CORE, max_bytes=100)
    assert result.ok is accepted


# ------------------------------------------------------------ the upload --
def test_an_expert_can_upload_a_single_cell_h5ad(client, expert_auth, tmp_path, monkeypatch):
    anndata = pytest.importorskip("anndata")
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    rng = np.random.default_rng(2)
    counts = rng.integers(0, 8, size=(40, 30))
    adata = anndata.AnnData(
        X=counts.astype(np.float32),
        obs=pd.DataFrame(
            {
                "sample_id": [f"donor{i % 4}" for i in range(40)],
                "condition": ["stimulated" if i % 4 in (1, 3) else "control" for i in range(40)],
            },
            index=[f"cell{i}" for i in range(40)],
        ),
        var=pd.DataFrame(index=[f"GENE{i}" for i in range(30)]),
    )
    path = tmp_path / "cells.h5ad"
    adata.write_h5ad(path)

    response = client.post(
        "/api/datasets/upload",
        headers=expert_auth,
        data={"track": "core", "name": "My cells", "source": "Lab archive", "accession": "LOCAL-SC-1", "license": "Internal teaching use"},
        files={"matrix": ("cells.h5ad", path.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 201, response.json()
    assert response.json()["validation"]["summary"]["n_samples"] == 4

    stored = [
        os.path.join(root, name)
        for root, _, files in os.walk(tmp_path / "uploads")
        for name in files
        if name.endswith(".npz")
    ]
    with np.load(stored[0]) as archive:
        assert archive["matrix"].shape == (40, 30)  # cells × genes, as the Core pipeline reads
