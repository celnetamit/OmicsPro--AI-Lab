"""Definition of Done: every adjustable parameter has a default, an allowed
range and a validation rule, and ranges are tier-constrained (spec 7, 13)."""

import pytest

from app.constants import AccessTier, AnalysisTrack
from app.core import parameters as params


def test_every_parameter_is_fully_specified():
    for parameter in params.REGISTRY.values():
        assert parameter.default is not None, parameter.key
        assert parameter.method_rule.strip(), parameter.key
        assert parameter.validation_message.strip(), parameter.key
        if parameter.kind in ("int", "float"):
            assert parameter.bounds_for("limited") is not None, parameter.key
        elif parameter.kind == "choice":
            assert parameter.choices is not None, parameter.key
        else:
            # bool, formula and dataset_choice carry no static range; their
            # validity is decided by type or by the selected dataset.
            assert parameter.kind in ("bool", "formula", "dataset_choice"), parameter.key


def test_defaults_are_inside_the_basic_range():
    """The guided default must be usable by the tier every learner has."""
    for parameter in params.REGISTRY.values():
        bounds = parameter.bounds_for("limited")
        if bounds:
            assert bounds[0] <= parameter.default <= bounds[1], parameter.key


def test_ranges_widen_with_tier():
    for parameter in params.REGISTRY.values():
        limited = parameter.bounds_for("limited")
        extended = parameter.bounds_for("extended")
        if limited and extended:
            assert extended[0] <= limited[0] and extended[1] >= limited[1], parameter.key


def test_tier_constrains_the_addressable_range():
    with pytest.raises(params.ParameterError):
        params.validate("sc.cluster.resolution", 2.5, AccessTier.BASIC)
    assert params.validate("sc.cluster.resolution", 2.5, AccessTier.MODERATE) == 2.5


def test_validation_message_names_the_bounds():
    with pytest.raises(params.ParameterError) as excinfo:
        params.validate("sc.qc.max_mito_pct", 99.0, AccessTier.BASIC)
    assert "2.0" in str(excinfo.value) and "15.0" in str(excinfo.value)


def test_cell_level_condition_testing_is_unreachable_at_every_tier():
    """Spec 4.2 hard rule, enforced by the registry rather than by copy."""
    for tier in AccessTier:
        with pytest.raises(params.ParameterError):
            params.validate("sc.de.grouping", "per_cell", tier)
        assert (
            params.validate("sc.de.grouping", "pseudobulk_by_sample", tier)
            == "pseudobulk_by_sample"
        )


def test_validate_many_fills_defaults_and_collects_errors():
    resolved = params.validate_many({}, AnalysisTrack.CORE, AccessTier.BASIC)
    assert resolved["sc.cluster.resolution"] == params.get("sc.cluster.resolution").default

    with pytest.raises(params.ParameterError) as excinfo:
        params.validate_many(
            {"sc.cluster.resolution": 99, "sc.qc.min_genes": 1},
            AnalysisTrack.CORE,
            AccessTier.BASIC,
        )
    assert set(excinfo.value.args[0]) == {"sc.cluster.resolution", "sc.qc.min_genes"}


def test_parameters_from_another_track_are_rejected():
    with pytest.raises(params.ParameterError) as excinfo:
        params.validate_many(
            {"bulk.de.fdr": 0.05}, AnalysisTrack.CORE, AccessTier.EXPERT
        )
    assert "bulk.de.fdr" in excinfo.value.args[0]


def test_panel_view_is_already_tier_constrained():
    basic = {p["key"]: p for p in params.describe_for(AnalysisTrack.CORE, AccessTier.BASIC)}
    expert = {p["key"]: p for p in params.describe_for(AnalysisTrack.CORE, AccessTier.EXPERT)}
    assert basic["sc.cluster.resolution"]["max"] < expert["sc.cluster.resolution"]["max"]
    assert basic["sc.cluster.resolution"]["caveat"]
