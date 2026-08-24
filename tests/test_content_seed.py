import ast
from datetime import datetime
import json
from pathlib import Path

import content_seed
import models
import pytest
from assessment.seed import load_core_catalog_manifest
from content_clock import SHANGHAI
from content_seed import CATALOG_SEED_PATH, ContentSeedError, seed_content_defaults


NOW = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)
KINDS = {"industry": "industries", "scenario": "scenarios", "service": "services"}
EXPECTED_TITLES = {
    "industry": {"制造业", "零售电商", "知识型专业服务", "软件与创意服务"},
    "scenario": {
        "制造知识助手", "制造质量检测", "制造经营报表", "零售智能服务",
        "零售营销内容协作", "零售库存洞察", "专业文档知识助手",
        "专业交付文稿协作", "专业合同审阅辅助", "创意内容工作流",
        "软件支持知识助手", "项目交付自动化", "数据与流程基础",
    },
    "service": {
        "AI 就绪基础工作坊", "企业知识助手试点", "客户增长助手试点",
        "流程自动化交付包", "数据洞察交付包", "行业场景集成交付包",
    },
}


def _catalog_rows(db):
    return db.execute(
        "SELECT g.entry_type,g.canonical_slug,ci.title,ci.summary,ci.status,ci.id "
        "FROM content_groups g JOIN content_items ci ON ci.content_group_id=g.id "
        "WHERE g.entry_type IN ('industry','scenario','service') "
        "ORDER BY g.entry_type,g.id"
    ).fetchall()


def test_checked_in_seed_has_exact_frozen_codes_slugs_titles_and_neutral_copy(db):
    manifest = load_core_catalog_manifest()
    seed = json.loads(CATALOG_SEED_PATH.read_text(encoding="utf-8"))

    assert seed["seed_version"] == "content_catalog_v1"
    assert seed["source"] == "reviewed-neutral-stage5a"
    for kind, manifest_key in KINDS.items():
        expected_codes = {row["code"] for row in manifest[manifest_key]}
        entries = seed[manifest_key]
        assert {row["code"] for row in entries} == expected_codes
        assert {row["slug"] for row in entries} == {
            code.replace("_", "-") for code in expected_codes
        }
        assert {row["title"] for row in entries} == EXPECTED_TITLES[kind]
        assert all(row["title"].strip() and row["summary"].strip() for row in entries)

    serialized = json.dumps(seed, ensure_ascii=False)
    for forbidden in ("客户案例", "客户数量", "成功率", "节省", "保证", "承诺", "法律意见"):
        assert forbidden not in serialized


def test_content_seed_is_dependency_free_of_flask_and_blueprints():
    source_path = Path(__file__).resolve().parents[1] / "content_seed.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name == "flask" or name.startswith("flask.") for name in imported)
    assert not any(name == "blueprints" or name.startswith("blueprints.") for name in imported)


def test_init_creates_exact_groups_and_one_draft_without_overwriting_operator_work(db):
    rows = _catalog_rows(db)
    assert len(rows) == 23
    assert {row["entry_type"] for row in rows} == set(KINDS)
    assert all(row["status"] == "draft" for row in rows)

    edited = rows[0]
    db.execute("UPDATE content_items SET title='运营已编辑',lock_version=2 WHERE id=?", (edited["id"],))
    db.commit()
    models.init_db()

    after = _catalog_rows(db)
    assert len(after) == 23
    assert tuple(db.execute("SELECT title,lock_version FROM content_items WHERE id=?", (edited["id"],)).fetchone()) == (
        "运营已编辑",
        2,
    )


def test_seed_never_revives_archive_or_creates_a_second_draft(db):
    item = db.execute(
        "SELECT id,content_group_id FROM content_items ORDER BY id LIMIT 1"
    ).fetchone()
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00' WHERE id=?",
        (item["id"],),
    )
    db.execute(
        "UPDATE content_items SET status='archived',archived_at='2026-08-24 10:00:01' WHERE id=?",
        (item["id"],),
    )
    db.commit()

    seed_content_defaults(db, now=NOW)
    db.commit()

    states = db.execute(
        "SELECT status FROM content_items WHERE content_group_id=? ORDER BY id",
        (item["content_group_id"],),
    ).fetchall()
    assert [row["status"] for row in states] == ["archived"]


def test_scenario_input_seed_prevalidates_every_entry_before_inserting(db, monkeypatch):
    payload = content_seed.load_scenario_input_seed()
    payload["scenarios"][-1]["inputs"] = [" "]
    before = db.execute("SELECT COUNT(*) FROM scenario_public_inputs").fetchone()[0]
    monkeypatch.setattr(content_seed, "load_scenario_input_seed", lambda: payload)

    with pytest.raises(ContentSeedError, match="scenario input seed values are invalid"):
        content_seed.seed_scenario_public_inputs(db)

    assert db.execute("SELECT COUNT(*) FROM scenario_public_inputs").fetchone()[0] == before


def test_scenario_input_seed_is_idempotent_and_preserves_draft_operator_input(db):
    draft = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' AND ci.status='draft'"
    ).fetchone()[0]
    db.execute(
        "UPDATE scenario_public_inputs SET input_text='运营审核后的输入' "
        "WHERE content_item_id=? AND sort_order=0", (draft,)
    )
    db.commit()

    seed_content_defaults(db, now=NOW)

    assert db.execute(
        "SELECT input_text FROM scenario_public_inputs WHERE content_item_id=? AND sort_order=0", (draft,)
    ).fetchone()[0] == "运营审核后的输入"
