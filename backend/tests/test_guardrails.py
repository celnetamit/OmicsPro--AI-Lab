"""Section 14 guardrails, enforced as tests so they cannot be skipped at review."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import lint_naming  # noqa: E402


def _scan_text(tmp_path, text, suffix=".py"):
    path = tmp_path / f"sample{suffix}"
    path.write_text(text)
    return lint_naming.scan([str(path)])


def test_the_repository_is_clean():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "lint_naming.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_a_tier_word_labelling_a_track_is_caught(tmp_path):
    findings = _scan_text(tmp_path, 'PIPELINES = {"expert_pipeline": run}\n')
    assert any(f[2] == "tier_word_in_scientific_context" for f in findings)


def test_a_track_word_labelling_a_tier_is_caught(tmp_path):
    findings = _scan_text(tmp_path, 'plan = "advanced"\ntier = "core"\n')
    assert any(f[2] == "track_word_in_commercial_context" for f in findings)


def test_an_upgrade_cta_using_a_track_name_is_caught(tmp_path):
    findings = _scan_text(tmp_path, "<p>Upgrade to Advanced for more runs</p>\n", ".tsx")
    assert any(f[2] == "track_word_in_commercial_context" for f in findings)


def test_a_hardcoded_threshold_is_caught(tmp_path):
    findings = _scan_text(tmp_path, "resolution = 1.4\nmax_mito = 5\n")
    assert len([f for f in findings if f[2] == "hardcoded_scientific_threshold"]) == 2


def test_the_registry_itself_is_allowlisted():
    findings = lint_naming.scan([os.path.join(ROOT, "backend", "app", "core", "parameters.py")])
    assert findings == []
