"""Dependency-free bootstrap for reviewed-neutral core catalog content."""

from datetime import datetime
import json
from pathlib import Path

from assessment.seed import load_core_catalog_manifest
from content_clock import as_shanghai
from content_contracts import ContentBlock, ContentDraft
from content_validation import is_exact_nonblank_text
import publishing_repository


CATALOG_SEED_PATH = Path(__file__).resolve().parent / "seed_data" / "content_catalog_v1.json"
SCENARIO_INPUT_SEED_PATH = Path(__file__).resolve().parent / "seed_data" / "scenario_public_inputs_v1.json"
SEED_VERSION = "content_catalog_v1"
SCENARIO_INPUT_SEED_VERSION = "scenario_public_inputs_v1"
SEED_SOURCE = "reviewed-neutral-stage5a"
CORE_KINDS = {
    "industry": ("industries", "industry_id"),
    "scenario": ("scenarios", "scenario_id"),
    "service": ("services", "service_id"),
}


class ContentSeedError(ValueError):
    """Raised before writes when the checked-in catalog and frozen core diverge."""


def load_content_seed():
    payload = json.loads(CATALOG_SEED_PATH.read_text(encoding="utf-8"))
    if payload.get("seed_version") != SEED_VERSION or payload.get("source") != SEED_SOURCE:
        raise ContentSeedError("content seed marker mismatch")
    return payload


def load_scenario_input_seed():
    payload = json.loads(SCENARIO_INPUT_SEED_PATH.read_text(encoding="utf-8"))
    if (
        type(payload) is not dict
        or set(payload) != {"seed_version", "source", "scenarios"}
        or payload.get("seed_version") != SCENARIO_INPUT_SEED_VERSION
        or payload.get("source") != SEED_SOURCE
    ):
        raise ContentSeedError("scenario input seed marker mismatch")
    return payload


def _validated_scenario_public_inputs():
    payload = load_scenario_input_seed()
    if type(payload) is not dict or set(payload) != {"seed_version", "source", "scenarios"}:
        raise ContentSeedError("scenario input seed container is invalid")
    entries = payload.get("scenarios")
    manifest_codes = {entry["code"] for entry in load_core_catalog_manifest()["scenarios"]}
    if type(entries) is not list or any(type(entry) is not dict for entry in entries):
        raise ContentSeedError("scenario input seed entries are invalid")
    if any(set(entry) != {"code", "inputs"} or type(entry.get("code")) is not str for entry in entries):
        raise ContentSeedError("scenario input seed entries are invalid")
    by_code = {entry["code"]: entry["inputs"] for entry in entries}
    if len(by_code) != len(entries) or set(by_code) != manifest_codes:
        raise ContentSeedError("scenario input seed codes differ from frozen catalog")
    validated = {}
    for code, inputs in by_code.items():
        if (
            type(inputs) is not list or not inputs
            or any(type(value) is not dict or set(value) != {"input_text", "sort_order"} for value in inputs)
        ):
            raise ContentSeedError("scenario input seed values are invalid")
        values = []
        for value in inputs:
            input_text = value["input_text"]
            sort_order = value["sort_order"]
            if (
                not is_exact_nonblank_text(input_text, maximum=300)
                or type(sort_order) is not int or sort_order < 1
            ):
                raise ContentSeedError("scenario input seed values are invalid")
            values.append((input_text, sort_order))
        if len({sort_order for _, sort_order in values}) != len(values):
            raise ContentSeedError("scenario input seed sort order is invalid")
        validated[code] = tuple(sorted(values, key=lambda value: value[1]))
    return validated


def seed_scenario_public_inputs(db):
    by_code = _validated_scenario_public_inputs()
    prepared = []
    for code, inputs in by_code.items():
        row = db.execute(
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code=? AND ci.status='draft'",
            (code,),
        ).fetchone()
        if row is None:
            continue
        if db.execute(
            "SELECT 1 FROM scenario_public_inputs WHERE content_item_id=? LIMIT 1", (row["id"],)
        ).fetchone() is None:
            prepared.append((row["id"], inputs))
    db.execute("SAVEPOINT scenario_public_input_seed")
    try:
        for content_item_id, inputs in prepared:
            db.executemany(
                "INSERT INTO scenario_public_inputs "
                "(content_item_id,input_text,sort_order) VALUES (?,?,?)",
                [(content_item_id, input_text, sort_order) for input_text, sort_order in inputs],
            )
    except Exception:
        db.execute("ROLLBACK TO scenario_public_input_seed")
        db.execute("RELEASE scenario_public_input_seed")
        raise
    db.execute("RELEASE scenario_public_input_seed")


def _core_rows(db, table):
    return {
        row["code"]: row
        for row in db.execute(
            f"SELECT * FROM {table} WHERE status='published' AND code IS NOT NULL "
            "ORDER BY sort_order,id"
        )
    }


def _validated_entries(db, payload):
    prepared = []
    frozen_manifest = load_core_catalog_manifest()
    for kind, (table, identity_column) in CORE_KINDS.items():
        all_core_by_code = _core_rows(db, table)
        frozen_codes = {entry["code"] for entry in frozen_manifest[table]}
        core_by_code = {
            code: all_core_by_code[code]
            for code in frozen_codes
            if code in all_core_by_code
        }
        entries = payload.get(table)
        if type(entries) is not list or any(type(entry) is not dict for entry in entries):
            raise ContentSeedError(f"{kind} seed entries are invalid")
        seed_by_code = {entry.get("code"): entry for entry in entries}
        if (
            len(seed_by_code) != len(entries)
            or set(seed_by_code) != frozen_codes
            or set(core_by_code) != frozen_codes
        ):
            raise ContentSeedError(f"{kind} seed codes differ from frozen catalog")
        for code, core_row in core_by_code.items():
            entry = seed_by_code[code]
            if entry.get("group") != f"{kind}:{code}":
                raise ContentSeedError(f"{kind} group marker is invalid")
            if entry.get("slug") != code.replace("_", "-"):
                raise ContentSeedError(f"{kind} slug is invalid")
            maturity_codes = entry.get("maturity_codes", [])
            if kind == "scenario" and not maturity_codes:
                raise ContentSeedError("scenario maturity choices are required")
            if kind != "scenario" and maturity_codes:
                raise ContentSeedError("maturity choices are scenario-only")
            prepared.append((kind, identity_column, core_row, entry))
    return tuple(prepared)


def _draft(kind, identity_column, core_row, entry, group_id=None):
    return ContentDraft(
        entry_type=kind,
        slug=entry["slug"],
        title=entry["title"],
        summary=entry["summary"],
        seo_title=entry["seo_title"],
        seo_description=entry["seo_description"],
        content_group_id=group_id,
        extension={identity_column: core_row["id"]},
        blocks=(
            ContentBlock(
                "rich_text",
                title="内容概述",
                body_html=entry["body_html"],
                settings={},
            ),
        ),
        maturity_codes=tuple(entry.get("maturity_codes", ())),
    )


def seed_content_defaults(db, now):
    """Create missing core groups and their first draft without committing."""
    if not isinstance(now, datetime):
        raise TypeError("now must be a timezone-aware datetime")
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_groups'"
    ).fetchone() is None:
        return
    instant = as_shanghai(now)
    payload = load_content_seed()
    prepared = _validated_entries(db, payload)
    for kind, identity_column, core_row, entry in prepared:
        group = db.execute(
            f"SELECT * FROM content_groups WHERE {identity_column}=?",
            (core_row["id"],),
        ).fetchone()
        if group is not None:
            existing = db.execute(
                "SELECT 1 FROM content_items WHERE content_group_id=? LIMIT 1",
                (group["id"],),
            ).fetchone()
            if existing is not None:
                continue
        publishing_repository.insert_content_draft(
            db,
            _draft(
                kind,
                identity_column,
                core_row,
                entry,
                group_id=group["id"] if group is not None else None,
            ),
            actor=SEED_SOURCE,
            now=instant,
        )
    seed_scenario_public_inputs(db)
