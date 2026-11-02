"""Shared pytest configuration for the code-only public repository."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# These tests assert against locally generated, third-party-derived datasets.
DATA_REQUIRED_TESTS = {
    "test_banlist.py",
    "test_bench.py",
    "test_cards_ingest.py",
    "test_engine_combat.py",
    "test_engine_deep.py",
    "test_engine_determinism.py",
    "test_engine_effects.py",
    "test_engine_fepr.py",
    "test_engine_integration.py",
    "test_engine_play.py",
    "test_engine_scoring.py",
    "test_engine_setup.py",
    "test_engine_turn.py",
    "test_errata.py",
    "test_faq.py",
    "test_qa.py",
    "test_qa_judge.py",
    "test_qa_zh.py",
    "test_rules_ingest.py",
}


def pytest_collection_modifyitems(config, items):
    """Skip data-backed tests when local third-party datasets are absent."""
    if (ROOT / "data").is_dir():
        return

    skip = pytest.mark.skip(
        reason="local third-party dataset missing; see docs/DATA_SETUP.md"
    )
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in DATA_REQUIRED_TESTS:
            item.add_marker(skip)