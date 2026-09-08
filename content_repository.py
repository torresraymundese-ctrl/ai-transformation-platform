"""Data access for public content, assessments, and CMS records."""

import catalog_content_repository as catalog
from admin_display import assessment_result_labels
from assessment_repository import MAX_REPORT_SNAPSHOT_BYTES
import case_repository as cases
from content_clock import as_shanghai, format_shanghai, shanghai_now
from content_validation import ContentValidationError
import legacy_content_migration
from models import get_db
from pagination import PageRequest
import publishing_repository
from repository import execute_write
import resource_repository as resources


def home_page_data(now=None):
    """Compose the homepage exclusively from fail-closed V2 public projections."""
    instant = now or shanghai_now()
    page = PageRequest(1, 20)
    return {
        "industries": catalog.public_industries(instant)[:6],
        "scenarios": catalog.public_scenarios(catalog.ScenarioFilters(), page, instant).items,
        "services": catalog.public_services(page, instant).items,
        "cases": cases.public_cases(page, instant).items,
        "resources": resources.list_published_resources(
            resources.ResourceFilters(None), page, now=instant
        ).items,
        "announcements": resources.list_current_announcements(now=instant)[:6],
    }


def services_by_tier():
    db = get_db()
    try:
        return {
            tier: db.execute(
                "SELECT * FROM services WHERE tier=? ORDER BY sort_order", (tier,)
            ).fetchall()
            for tier in ("starter", "accelerate", "flagship")
        }
    finally:
        db.close()


def search_cases(industry, search):
    query = "SELECT * FROM cases WHERE 1=1"
    params = []
    if industry:
        query += " AND industry=?"
        params.append(industry)
    if search:
        query += (
            " AND (title LIKE ? OR pain_point LIKE ? OR solution LIKE ? "
            "OR result LIKE ? OR tags LIKE ?)"
        )
        params.extend([f"%{search}%"] * 5)
    query += " ORDER BY sort_order"
    db = get_db()
    try:
        return (
            db.execute(query, params).fetchall(),
            db.execute("SELECT DISTINCT industry FROM cases ORDER BY industry").fetchall(),
        )
    finally:
        db.close()


def insight_page_data(category, tag, search):
    if category == "announcement":
        query = (
            "SELECT * FROM articles WHERE status='published' "
            "AND category='announcement'"
        )
        params = []
    else:
        query = (
            "SELECT * FROM articles WHERE status='published' "
            "AND category!='announcement'"
        )
        params = []
        if category:
            query += " AND category=?"
            params.append(category)
        if tag:
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")
        if search:
            query += " AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?)"
            params.extend([f"%{search}%"] * 3)
    query += " ORDER BY created_at DESC LIMIT 50"
    db = get_db()
    try:
        return {
            "articles": db.execute(query, params).fetchall(),
            "announcements": db.execute(
                "SELECT * FROM announcements WHERE status='published' "
                "ORDER BY is_pinned DESC, created_at DESC"
            ).fetchall(),
        }
    finally:
        db.close()


def article_detail(article_id):
    db = get_db()
    try:
        article = db.execute(
            "SELECT * FROM articles WHERE id=?", (article_id,)
        ).fetchone()
        if article is None:
            return None, []
        related = db.execute(
            "SELECT * FROM articles WHERE status='published' AND id!=? "
            "ORDER BY created_at DESC LIMIT 4",
            (article_id,),
        ).fetchall()
        return article, related
    finally:
        db.close()


def legacy_article_resource_slug(article_id, now=None):
    """Resolve one checksum-current clean mapping in one SQLite read snapshot."""
    if type(article_id) is not int or not 1 <= article_id <= 2**63 - 1:
        return None
    instant = as_shanghai(now or shanghai_now())
    db = get_db()
    try:
        db.execute("BEGIN")
        source = db.execute(
            "SELECT * FROM articles WHERE id=?", (article_id,)
        ).fetchone()
        if source is None:
            return None
        checksum = legacy_content_migration._canonical_checksum("articles", source)
        mapping = db.execute(
            "SELECT m.target_content_group_id,m.target_content_item_id,"
            "g.canonical_slug,mapped.content_group_id AS mapped_group_id,"
            "mapped.entry_type AS mapped_entry_type "
            "FROM legacy_content_reviews review "
            "JOIN legacy_content_mappings m ON m.source_table=review.source_table "
            "AND m.source_id=review.source_id "
            "JOIN content_groups g ON g.id=m.target_content_group_id "
            "JOIN content_items mapped ON mapped.id=m.target_content_item_id "
            "WHERE review.source_table='articles' AND review.source_id=? "
            "AND review.decision_action='clean' AND review.target_type='resource' "
            "AND review.target_group IS NULL AND review.review_stale_at IS NULL "
            "AND review.source_checksum=? AND review.decision_source_checksum=? "
            "AND m.source_checksum=? AND g.entry_type='resource'",
            (article_id, checksum, checksum, checksum),
        ).fetchone()
        if (
            mapping is None
            or mapping["mapped_group_id"] != mapping["target_content_group_id"]
            or mapping["mapped_entry_type"] != "resource"
        ):
            return None
        current = db.execute(
            "SELECT id,slug FROM content_items WHERE content_group_id=? "
            "AND entry_type='resource' AND status='published' "
            "AND (publish_at IS NULL OR publish_at<=?)",
            (mapping["target_content_group_id"], format_shanghai(instant)),
        ).fetchone()
        if current is None or current["slug"] != mapping["canonical_slug"]:
            return None
        try:
            publishing_repository.validate_resource_public_completeness(
                db, current["id"], instant
            )
        except (ContentValidationError, TypeError, ValueError):
            return None
        return current["slug"]
    finally:
        db.rollback()
        db.close()


def create_assessment(company, email, scores_json, result):
    return execute_write(
        "INSERT INTO assessments (company_name,contact_email,scores,result) "
        "VALUES (?,?,?,?)",
        (company, email, scores_json, result),
    )


def admin_counts():
    db = get_db()
    try:
        return {
            "articles": db.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "cases": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
            "assessments": db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0],
        }
    finally:
        db.close()


def list_articles():
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM articles ORDER BY created_at DESC"
        ).fetchall()
    finally:
        db.close()


def get_article(article_id):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM articles WHERE id=?", (article_id,)
        ).fetchone()
    finally:
        db.close()


def create_article(item):
    return execute_write(
        "INSERT INTO articles (title_hash,title,source,source_url,summary,content_html,"
        "tags,category,is_featured,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            item["title_hash"], item["title"], item["source"], item["source_url"],
            item["summary"], item["content_html"], item["tags"], item["category"],
            item["is_featured"], item["status"],
        ),
    )


def update_article(article_id, item):
    execute_write(
        "UPDATE articles SET title=?,source=?,source_url=?,summary=?,content_html=?,"
        "tags=?,category=?,is_featured=?,status=? WHERE id=?",
        (
            item["title"], item["source"], item["source_url"], item["summary"],
            item["content_html"], item["tags"], item["category"],
            item["is_featured"], item["status"], article_id,
        ),
    )


def list_cases():
    db = get_db()
    try:
        return db.execute("SELECT * FROM cases ORDER BY sort_order").fetchall()
    finally:
        db.close()


def get_case(case_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    finally:
        db.close()


def create_case(item):
    return execute_write(
        "INSERT INTO cases (title,industry,scale,pain_point,solution,result,tags,logo_text) "
        "VALUES (?,?,?,?,?,?,?,?)",
        tuple(item.values()),
    )


def update_case(case_id, item):
    execute_write(
        "UPDATE cases SET title=?,industry=?,scale=?,pain_point=?,solution=?,result=?,"
        "tags=?,logo_text=? WHERE id=?",
        (*item.values(), case_id),
    )


def list_assessments(limit=50):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT a.id,a.created_at,a.lead_id,a.submission_key,l.id AS linked_lead_id,l.anonymized_at,"
            "CASE WHEN a.lead_id IS NULL AND a.submission_key IS NULL THEN a.company_name "
            "WHEN l.id IS NULL THEN '线索已不存在' "
            "WHEN l.anonymized_at IS NOT NULL THEN '已匿名化' "
            "ELSE l.company_name END AS company_name,"
            "CASE WHEN a.lead_id IS NULL AND a.submission_key IS NULL THEN a.contact_email "
            "WHEN l.anonymized_at IS NULL THEN l.email END AS contact_email,"
            "CASE WHEN a.lead_id IS NULL AND a.submission_key IS NULL THEN a.result END AS result,"
            "CASE WHEN length(CAST(a.report_snapshot_json AS BLOB))<=? "
            "THEN a.report_snapshot_json END AS report_snapshot_json "
            "FROM assessments a LEFT JOIN leads l ON l.id=a.lead_id "
            "ORDER BY a.created_at DESC,a.id DESC LIMIT ?",
            (MAX_REPORT_SNAPSHOT_BYTES, limit),
        ).fetchall()
    finally:
        db.close()
    items = []
    for row in rows:
        item = dict(row)
        raw = item.pop("report_snapshot_json")
        item["package_name"] = None
        if item["lead_id"] is not None or item["submission_key"] is not None:
            item["result"], item["package_name"] = assessment_result_labels(raw)
        items.append(item)
    return items


def list_announcements():
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM announcements ORDER BY created_at DESC"
        ).fetchall()
    finally:
        db.close()


def get_announcement(announcement_id):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM announcements WHERE id=?", (announcement_id,)
        ).fetchone()
    finally:
        db.close()


def create_announcement(item):
    return execute_write(
        "INSERT INTO announcements (title,content_html,is_pinned,status) VALUES (?,?,?,?)",
        tuple(item.values()),
    )


def update_announcement(announcement_id, item):
    execute_write(
        "UPDATE announcements SET title=?,content_html=?,is_pinned=?,status=? WHERE id=?",
        (*item.values(), announcement_id),
    )
