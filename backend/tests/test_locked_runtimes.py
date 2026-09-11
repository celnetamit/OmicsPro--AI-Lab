"""Spec 10, 14.6: a locked method runs at its locked version or not at all.

A run records the method version that produced it, so an adapter checks the
installed release against the lock instead of trusting whatever is present.
"""

import sys
import types

import numpy as np
import pytest

from app.pipelines import locked
from app.pipelines.base import BackendUnavailable


def _fake_r_runtime(monkeypatch, deseq2_version: str) -> None:
    rpy2 = types.ModuleType("rpy2")
    robjects = types.ModuleType("rpy2.robjects")
    packages = types.ModuleType("rpy2.robjects.packages")
    robjects.r = lambda expression: [deseq2_version]
    packages.importr = lambda name: object()
    robjects.packages = packages
    rpy2.robjects = robjects
    monkeypatch.setitem(sys.modules, "rpy2", rpy2)
    monkeypatch.setitem(sys.modules, "rpy2.robjects", robjects)
    monkeypatch.setitem(sys.modules, "rpy2.robjects.packages", packages)


def test_a_deseq2_release_other_than_the_lock_is_refused(monkeypatch):
    _fake_r_runtime(monkeypatch, "1.40.2")
    with pytest.raises(BackendUnavailable) as refused:
        locked.deseq2_differential_expression(
            np.ones((3, 4)), ["A", "B", "C"], [{}] * 4, "~ condition", "control"
        )
    assert "DESeq2 1.40.2 is installed" in str(refused.value)


def test_the_embedding_runtime_is_checked_the_same_way(monkeypatch):
    fake = types.ModuleType("umap")
    fake.__version__ = "0.5.0"
    fake.UMAP = object
    monkeypatch.setitem(sys.modules, "umap", fake)
    with pytest.raises(BackendUnavailable) as refused:
        locked.umap_embedding(np.zeros((10, 3)), 5, 0.5)
    assert "0.5.0" in str(refused.value)
