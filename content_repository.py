"""Data access for public content, assessments, and CMS records."""

from models import get_db
from repository import execute_write


def home_page_data():
    db = get_db()
    try:
        return {
            "cases": db.execute(
                "SELECT * FROM cases WHERE is_featured=1 ORDER BY sort_order LIMIT 3"
            ).fetchall(),
            "services": db.execute(
                "SELECT * FROM services ORDER BY sort_order"
            ).fetchall(),
            "articles": db.execute(
                "SELECT * FROM articles WHERE status='published' "
                "ORDER BY created_at DESC LIMIT 6"
            ).fetchall(),
        }
    finally:
        db.close()


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
        return db.execute(
            "SELECT * FROM assessments ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        db.close()


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
