"""Catalog: positive (loads the shipped sample) + negative (malformed rejected)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sapgui_mcp.catalog import load_catalog

SAMPLE = Path(__file__).resolve().parents[1] / "catalog" / "catalog.json"


# -- positive -----------------------------------------------------------------

def test_loads_shipped_catalog() -> None:
    cat = load_catalog(SAMPLE)
    assert cat.version == 1
    assert "create_sales_order" in cat.tasks


def test_lookup_by_alias() -> None:
    cat = load_catalog(SAMPLE)
    assert cat.lookup("VA01", "ANY") is not None  # alias of create_sales_order


def test_system_override_applied() -> None:
    cat = load_catalog(SAMPLE)
    base = cat.lookup("create_sales_order", "OTHER")
    overridden = cat.lookup("create_sales_order", "S4P")
    assert base is not None and overridden is not None
    assert base.tier2.buggy == []
    assert "schedule_lines_tab" in overridden.tier2.buggy


def test_shipped_catalog_survives_save_load_roundtrip(tmp_path: Path) -> None:
    """Learning rewrites this file — a dump must always re-validate on load."""
    from sapgui_mcp.catalog import save_catalog

    original = load_catalog(SAMPLE)
    out = tmp_path / "roundtrip.json"
    save_catalog(original, out)
    assert load_catalog(out).model_dump() == original.model_dump()


def test_unknown_task_returns_none() -> None:
    cat = load_catalog(SAMPLE)
    assert cat.lookup("does_not_exist", "ANY") is None


# -- negative -----------------------------------------------------------------

def test_malformed_extra_field_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1, "tasks": {"x": {"bogus_field": 1}}}))
    with pytest.raises(ValidationError):
        load_catalog(bad)


def test_missing_version_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"tasks": {}}))
    with pytest.raises(ValidationError):
        load_catalog(bad)


def test_unknown_preferred_order_token_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "version": 1,
        "tasks": {"x": {"preferred_order": ["tier9.magic"]}},
    }))
    with pytest.raises(ValueError):
        load_catalog(bad)


def test_bad_json_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        load_catalog(bad)
