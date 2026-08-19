#!/usr/bin/env python                # ✅ 指定 Python 解释器路径（跨平台兼容）
# -*- coding: utf-8 -*-               # ✅ 文件编码声明（支持中文）
"""企业AI转型平台 — Flask 后端主程序"""  # ✅ 模块说明文档

# === 标准库导入 ===
import sys                              # 系统操作：路径管理
import os                               # 文件系统：路径拼接
import json                             # JSON 数据：序列化/反序列化
import sqlite3                          # SQLite 数据库驱动（备用）
import hashlib
import re
import secrets
import time
from datetime import timedelta
from hmac import compare_digest

# === 第三方库导入 ===
import bleach
from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash
# 上述导入: Flask(核心) render_template(模板) request(请求) jsonify(JSON响应) redirect(重定向) url_for(路由URL)

# === 本地模块导入 ===
sys.path.insert(0, os.path.dirname(__file__))  # 将当前目录加入 Python 搜索路径
from models import get_db, init_db              # 导入数据库连接和初始化函数

app = Flask(__name__)                   # ✅ 创建 Flask 应用实例
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# === 安全配置与后台鉴权 ===
app.config.update(
    SECRET_KEY=os.environ.get("AI_PLATFORM_SECRET_KEY"),
    ADMIN_USERNAME=os.environ.get("AI_PLATFORM_ADMIN_USERNAME"),
    ADMIN_PASSWORD_HASH=os.environ.get("AI_PLATFORM_ADMIN_PASSWORD_HASH"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=1024 * 1024,
    LOGIN_RATE_LIMIT=10,
    LOGIN_RATE_WINDOW=15 * 60,
    ASSESSMENT_RATE_LIMIT=30,
    ASSESSMENT_RATE_WINDOW=60 * 60,
    SCRAPE_RATE_LIMIT=3,
    SCRAPE_RATE_WINDOW=60 * 60,
)

ALLOWED_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h2", "h3", "h4", "hr",
    "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
    "thead", "tr", "ul",
}
ALLOWED_HTML_ATTRIBUTES = {
    "a": ["href", "title"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def security_configured():
    """Return whether the admin can authenticate without unsafe defaults."""
    return bool(
        app.config.get("SECRET_KEY")
        and app.config.get("ADMIN_USERNAME")
        and app.config.get("ADMIN_PASSWORD_HASH")
    )


def csrf_token():
    """Return a session-bound CSRF token for forms and JavaScript requests."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_is_valid():
    """Compare submitted and session tokens without timing-dependent equality."""
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get(
        "X-CSRF-Token", ""
    )
    return bool(expected and supplied and compare_digest(expected, supplied))


def check_admin_auth():
    """Check the signed browser session rather than an Authorization header."""
    return (
        security_configured()
        and session.get("admin_username") == app.config["ADMIN_USERNAME"]
    )


def request_identity_hash():
    """Hash the network identifier so raw client addresses are not persisted."""
    identifier = request.remote_addr or "unknown"
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]


def consume_rate_limit(bucket, limit, window_seconds):
    """Atomically consume one fixed-window allowance in the shared SQLite DB."""
    limit = int(limit)
    window_seconds = int(window_seconds)
    if limit < 1 or window_seconds < 1:
        return False

    now = int(time.time())
    window_start = now - (now % window_seconds)
    identity_hash = request_identity_hash()
    db = get_db()
    try:
        db.execute(
            "INSERT INTO request_rate_limits "
            "(bucket, identity_hash, window_start, request_count) VALUES (?,?,?,1) "
            "ON CONFLICT(bucket, identity_hash, window_start) "
            "DO UPDATE SET request_count=request_count+1",
            (bucket, identity_hash, window_start),
        )
        count = db.execute(
            "SELECT request_count FROM request_rate_limits "
            "WHERE bucket=? AND identity_hash=? AND window_start=?",
            (bucket, identity_hash, window_start),
        ).fetchone()[0]
        db.execute(
            "DELETE FROM request_rate_limits WHERE window_start < ?",
            (window_start - window_seconds,),
        )
        db.commit()
    finally:
        db.close()
    return count <= limit


def rate_limit_response(window_seconds):
    response = jsonify({"error": "rate limit exceeded"})
    response.status_code = 429
    response.headers["Retry-After"] = str(int(window_seconds))
    return response


def sanitize_html(value):
    """Clean stored rich text using a small content-oriented allowlist."""
    without_active_blocks = re.sub(
        r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", "", value or ""
    )
    cleaned = bleach.clean(
        without_active_blocks,
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return Markup(cleaned)


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.filters["safe_html"] = sanitize_html


@app.before_request
def protect_admin_routes():
    """Fail closed, require a signed session, and protect all admin writes."""
    if not request.path.startswith("/admin"):
        return None

    if not security_configured():
        return "后台安全配置未完成", 503

    if request.path == "/admin/login":
        if request.method == "POST" and not csrf_is_valid():
            abort(403)
        if request.method == "POST" and not consume_rate_limit(
            "admin_login",
            app.config["LOGIN_RATE_LIMIT"],
            app.config["LOGIN_RATE_WINDOW"],
        ):
            return rate_limit_response(app.config["LOGIN_RATE_WINDOW"])
        return None

    if not check_admin_auth():
        return redirect(url_for("admin_login", next=request.path))

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not csrf_is_valid():
        abort(403)
    if request.path == "/admin/scrape" and request.method == "POST":
        if not consume_rate_limit(
            "admin_scrape",
            app.config["SCRAPE_RATE_LIMIT"],
            app.config["SCRAPE_RATE_WINDOW"],
        ):
            return rate_limit_response(app.config["SCRAPE_RATE_WINDOW"])
    return None


@app.after_request
def add_security_headers(response):
    """Apply browser hardening headers without breaking the legacy inline UI."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    return response


@app.after_request
def audit_admin_actions(response):
    """Record minimal metadata for admin state changes, including rejections."""
    if request.path.startswith("/admin") and request.method in {
        "POST", "PUT", "PATCH", "DELETE"
    }:
        actor = getattr(g, "audit_actor", None) or session.get(
            "admin_username"
        ) or request.form.get("username", "anonymous")[:80]
        action = request.endpoint or "unmatched_admin_request"
        db = None
        try:
            db = get_db()
            db.execute(
                "INSERT INTO admin_audit_logs "
                "(actor, action, status_code, ip_hash) VALUES (?,?,?,?)",
                (actor, action, response.status_code, request_identity_hash()),
            )
            db.commit()
        except sqlite3.Error:
            app.logger.exception("Failed to write admin audit event")
        finally:
            if db is not None:
                db.close()
    return response


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Authenticate an administrator against the configured password hash."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        username_ok = compare_digest(username, app.config["ADMIN_USERNAME"])
        password_ok = check_password_hash(app.config["ADMIN_PASSWORD_HASH"], password)
        if not (username_ok and password_ok):
            return render_template("admin/login.html", error="账号或密码错误"), 401

        session.clear()
        session["admin_username"] = app.config["ADMIN_USERNAME"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("admin_index"))

    if check_admin_auth():
        return redirect(url_for("admin_index"))
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    """Revoke the current administrator session."""
    g.audit_actor = session.get("admin_username", "anonymous")
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/health")                   # 🩺 健康检查端点（供监控系统探测）
def health():
    return jsonify({"status": "ok"})    # 返回 JSON 表示服务正常运行

# ========== 模板辅助函数 ==========

def svc_emoji(icon):                    # 🎨 服务图标映射函数
    """将 models.py 中存储的图标标识符映射为对应的 emoji 表情"""
    mapping = {                         # 图标标识符 → emoji 映射字典
        "database":"🗄️",                # 数据治理
        "server":"🖥️",                   # 本地大模型部署
        "book":"📚",                     # RAG 知识库
        "file-text":"📝",               # AI 办公助手
        "target":"🎯",                   # 垂直行业 RAG
        "cpu":"🤖",                      # AI Agent 智能体
        "repeat":"🔄",                   # RPA 流程自动化
        "trending-up":"📈",              # 数据决策 AI
        "layers":"🏗️",                  # AI 私有中台
        "eye":"👁️",                      # 多模态 AI
        "shield":"🛡️",                   # 安全合规
        "users":"👥"                     # 战略咨询培训
    }
    return mapping.get(icon, "📌")       # 未匹配时返回 📌 作为默认图标

app.jinja_env.globals["svc_emoji"] = svc_emoji  # ✅ 注册为 Jinja2 全局函数，模板中可直接调用

# ========== 前端公开页面路由 ==========

@app.route("/")                         # 🏠 首页路由
def index():
    """首页：展示精选案例 + 三层服务 + 最新资讯"""
    db = get_db()                       # 获取数据库连接
    # 查询 3 条精选案例（is_featured=1 且按排序号排列）
    featured_cases = db.execute(
        "SELECT * FROM cases WHERE is_featured=1 ORDER BY sort_order LIMIT 3"
    ).fetchall()
    # 查询全部服务方案（按排序号排列）
    services = db.execute(
        "SELECT * FROM services ORDER BY sort_order"
    ).fetchall()
    # 查询最新 6 篇已发布文章
    articles = db.execute(
        "SELECT * FROM articles WHERE status='published' ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    db.close()                          # 关闭数据库连接
    return render_template("index.html",  # 渲染首页模板
                           cases=featured_cases,   # 传递给模板的案例数据
                           services=services,      # 传递给模板的服务数据
                           articles=articles)      # 传递给模板的文章数据

@app.route("/services")                 # 📦 服务方案页路由
def services_page():
    """服务方案页：按三层（启航/加速/旗舰）分别展示服务卡片"""
    db = get_db()
    # 查询启航包（tier='starter'）
    starter = db.execute(
        "SELECT * FROM services WHERE tier='starter' ORDER BY sort_order"
    ).fetchall()
    # 查询加速包（tier='accelerate'）
    accelerate = db.execute(
        "SELECT * FROM services WHERE tier='accelerate' ORDER BY sort_order"
    ).fetchall()
    # 查询旗舰包（tier='flagship'）
    flagship = db.execute(
        "SELECT * FROM services WHERE tier='flagship' ORDER BY sort_order"
    ).fetchall()
    db.close()
    return render_template("services.html",         # 渲染服务方案模板
                           starter=starter,         # 启航包数据
                           accelerate=accelerate,   # 加速包数据
                           flagship=flagship)       # 旗舰包数据

@app.route("/cases")                    # 📋 案例库页路由
def cases_page():
    """案例库页：按行业筛选 + 关键词搜索，展示 27 个真实企业案例"""
    db = get_db()
    # === URL 参数获取 ===
    industry = request.args.get("industry", "")   # 行业筛选参数
    search = request.args.get("search", "")       # 关键词搜索参数
    # === 动态构建 SQL 查询 ===
    query = "SELECT * FROM cases WHERE 1=1"       # 基础查询（1=1 方便动态拼接 AND）
    params = []                                    # SQL 参数列表
    if industry:                                   # 如果有行业筛选
        query += " AND industry=?"                 # 拼接行业条件
        params.append(industry)
    if search:                                     # 如果有搜索关键词
        # 在标题/痛点/方案/效果/标签五个字段中模糊搜索
        query += " AND (title LIKE ? OR pain_point LIKE ? OR solution LIKE ? OR result LIKE ? OR tags LIKE ?)"
        params.extend([f"%{search}%"] * 5)         # 将同一个关键词重复 5 次
    query += " ORDER BY sort_order"                # 按排序号排列
    cases = db.execute(query, params).fetchall()   # 执行查询
    # 查询所有不重复的行业（用于筛选标签栏）
    industries = db.execute(
        "SELECT DISTINCT industry FROM cases ORDER BY industry"
    ).fetchall()
    db.close()
    return render_template("cases.html",            # 渲染案例库模板
                           cases=cases,             # 案例列表
                           industries=industries,   # 行业列表
                           current_industry=industry, # 当前筛选行业
                           search=search)           # 当前搜索词

@app.route("/assessment")               # 📊 企业AI就绪度评估页路由
def assessment_page():
    """评估页：行业定制化评估问卷，纯前端 JS 交互"""
    return render_template("assessment.html")       # 页面逻辑由 JS 驱动

@app.route("/api/assessment", methods=["POST"])  # 📡 评估数据提交接口（仅接收 POST）
def api_assessment():
    """接收前端提交的评估结果，存储到数据库"""
    if not consume_rate_limit(
        "assessment",
        app.config["ASSESSMENT_RATE_LIMIT"],
        app.config["ASSESSMENT_RATE_WINDOW"],
    ):
        return rate_limit_response(app.config["ASSESSMENT_RATE_WINDOW"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid assessment payload"}), 400

    company = data.get("company", "")
    email = data.get("email", "")
    scores = data.get("scores")
    result = data.get("result", "")
    if not isinstance(company, str) or len(company.strip()) > 120:
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(email, str) or len(email.strip()) > 254:
        return jsonify({"error": "invalid assessment payload"}), 400
    if email.strip() and not EMAIL_PATTERN.fullmatch(email.strip()):
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(scores, dict) or not scores:
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(result, str) or not result.strip() or len(result.strip()) > 120:
        return jsonify({"error": "invalid assessment payload"}), 400
    try:
        scores_json = json.dumps(scores, ensure_ascii=False)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid assessment payload"}), 400
    if len(scores_json.encode("utf-8")) > 16 * 1024:
        return jsonify({"error": "invalid assessment payload"}), 400

    db = get_db()
    # 将评估记录写入 assessments 表
    db.execute(
        "INSERT INTO assessments (company_name, contact_email, scores, result) VALUES (?,?,?,?)",
        (company.strip(),                 # 公司名
         email.strip().lower(),           # 邮箱
         scores_json,                     # 评分数据 JSON 序列化
         result.strip())                  # 推荐方案等级
    )
    db.commit()                         # 提交事务
    db.close()
    return jsonify({"success": True})   # 返回成功响应

@app.route("/insights")                 # 📰 资讯页路由
def insights_page():
    """资讯页：支持分类筛选 + 标签筛选 + 全文搜索"""
    db = get_db()
    # === URL 参数获取 ===
    category = request.args.get("category", "")   # 分类筛选
    tag = request.args.get("tag", "")              # 标签筛选
    search = request.args.get("search", "")        # 全文搜索
    # === 公告专区处理 ===
    if category == "announcement":                 # 如果用户点"公告"标签
        query = "SELECT * FROM articles WHERE status='published' AND category='announcement'"
        params = []
    else:
        # === 资讯区（排除公告）多条件筛选 ===
        query = "SELECT * FROM articles WHERE status='published' AND category!='announcement'"
        params = []
        if category:                               # 按分类筛选
            query += " AND category=?"
            params.append(category)
        if tag:                                    # 按标签模糊搜索
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")
        if search:                                 # 全文搜索（标题/摘要/标签）
            query += " AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?)"
            params.extend([f"%{search}%"] * 3)
    query += " ORDER BY created_at DESC LIMIT 50"  # 最新 50 篇
    articles = db.execute(query, params).fetchall()
    # 查询已发布的公告（置顶优先，然后按时间倒序）
    announcements = db.execute(
        "SELECT * FROM announcements WHERE status='published' ORDER BY is_pinned DESC, created_at DESC"
    ).fetchall()
    db.close()
    return render_template("insights.html",
                           articles=articles,
                           current_category=category,
                           current_tag=tag,
                           announcements=announcements,
                           search=search)

@app.route("/article/<int:article_id>")  # 📄 文章详情页路由（动态路由参数）
def article_page(article_id):
    """文章详情页：展示全文 + 相关文章推荐"""
    db = get_db()
    # 查询指定 ID 的文章
    article = db.execute(
        "SELECT * FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    if not article:                     # 文章不存在时
        db.close()
        return "Article not found", 404 # 返回 404 错误
    # 查询 4 篇相关文章（发表时间最近的，排除当前文章）
    related = db.execute(
        "SELECT * FROM articles WHERE status='published' AND id!=? ORDER BY created_at DESC LIMIT 4",
        (article_id,)
    ).fetchall()
    db.close()
    return render_template("article.html",
                           article=article,
                           related=related)

@app.route("/about")                    # ℹ️ 关于我们页路由
def about_page():
    """关于我们页：公司信息、核心原则、联系方式"""
    return render_template("about.html")

# ========== 管理后台路由（CMS 内容管理系统） ==========

@app.route("/admin")                    # 🖥️ 后台首页/控制台
def admin_index():
    """后台控制台：展示文章数、案例数、评估记录数"""
    db = get_db()
    article_count = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    case_count = db.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assessment_count = db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    db.close()
    return render_template("admin/index.html",
                           stats={"articles": article_count,
                                  "cases": case_count,
                                  "assessments": assessment_count})

# === 文章管理 ===

@app.route("/admin/articles")           # 📝 文章列表页
def admin_articles():
    """后台文章列表：按创建时间倒序展示"""
    db = get_db()
    articles = db.execute(
        "SELECT * FROM articles ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return render_template("admin/articles.html", articles=articles)

@app.route("/admin/article/<int:article_id>", methods=["GET","POST"])  # ✏️ 编辑文章
def admin_article_edit(article_id):
    """后台编辑文章：GET 展示表单，POST 保存更新"""
    db = get_db()
    if request.method == "POST":        # POST 请求 = 保存修改
        data = request.form             # 获取表单数据
        # 更新文章所有字段
        db.execute(
            "UPDATE articles SET title=?,source=?,source_url=?,summary=?,content_html=?,tags=?,category=?,is_featured=?,status=? WHERE id=?",
            (data.get("title"),           # 标题
             data.get("source"),          # 来源
             data.get("source_url"),      # 来源链接
             data.get("summary"),         # 摘要
             str(sanitize_html(data.get("content_html"))),  # 已清洗正文 HTML
             data.get("tags"),            # 标签
             data.get("category"),        # 分类
             int(data.get("is_featured",0)),  # 是否精选
             data.get("status"),          # 状态
             article_id))
        db.commit()
        db.close()
        return redirect(url_for("admin_articles"))  # 重定向回文章列表
    # GET 请求 = 展示编辑表单
    article = db.execute(
        "SELECT * FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    db.close()
    return render_template("admin/article_edit.html", article=article)

@app.route("/admin/article/new", methods=["GET","POST"])  # ➕ 新建文章
def admin_article_new():
    """后台新建文章：GET 展示空表单，POST 插入新记录"""
    if request.method == "POST":
        db = get_db()
        data = request.form
        import hashlib
        # 用标题 MD5 生成唯一标识（防止重复抓取同一篇文章）
        title_hash = hashlib.md5(data.get("title","").encode()).hexdigest()[:16]
        db.execute(
            "INSERT INTO articles (title_hash,title,source,source_url,summary,content_html,tags,category,is_featured,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title_hash,
             data.get("title"),
             data.get("source"),
             data.get("source_url"),
             data.get("summary"),
             str(sanitize_html(data.get("content_html"))),
             data.get("tags"),
             data.get("category"),
             int(data.get("is_featured",0)),
             data.get("status")))
        db.commit(); db.close()
        return redirect("/admin/articles")
    return render_template("admin/article_edit.html", article=None)  # article=None 表示新建模式

# === 案例管理 ===

@app.route("/admin/cases")              # 📋 案例列表页
def admin_cases():
    """后台案例列表"""
    db = get_db()
    cases = db.execute("SELECT * FROM cases ORDER BY sort_order").fetchall()
    db.close()
    return render_template("admin/cases.html", cases=cases)

@app.route("/admin/case/new", methods=["GET","POST"])  # ➕ 新建案例
def admin_case_new():
    """后台新建案例"""
    if request.method == "POST":
        db = get_db()
        data = request.form
        db.execute(
            "INSERT INTO cases (title,industry,scale,pain_point,solution,result,tags,logo_text) VALUES (?,?,?,?,?,?,?,?)",
            (data.get("title"),
             data.get("industry"),
             data.get("scale"),
             data.get("pain_point"),
             data.get("solution"),
             data.get("result"),
             data.get("tags"),
             data.get("logo_text","E")))
        db.commit(); db.close()
        return redirect("/admin/cases")
    return render_template("admin/case_edit.html", case=None)

@app.route("/admin/case/<int:case_id>", methods=["GET","POST"])  # ✏️ 编辑案例
def admin_case_edit(case_id):
    """后台编辑案例"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE cases SET title=?,industry=?,scale=?,pain_point=?,solution=?,result=?,tags=?,logo_text=? WHERE id=?",
            (data.get("title"),
             data.get("industry"),
             data.get("scale"),
             data.get("pain_point"),
             data.get("solution"),
             data.get("result"),
             data.get("tags"),
             data.get("logo_text"), case_id))
        db.commit(); db.close()
        return redirect("/admin/cases")
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    db.close()
    return render_template("admin/case_edit.html", case=case)

# === 评估记录 ===

@app.route("/admin/assessments")        # 📊 评估记录列表
def admin_assessments():
    """后台评估记录：展示最新 50 条"""
    db = get_db()
    assessments = db.execute(
        "SELECT * FROM assessments ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    db.close()
    return render_template("admin/assessments.html", assessments=assessments)

# === 内容抓取 ===

@app.route("/admin/scrape", methods=["POST"])  # 🔄 触发内容抓取
def admin_scrape():
    """后台手动触发文章抓取（调用 scraper.py 的 run_scraper）"""
    try:
        from scraper import run_scraper
        count = run_scraper()           # 执行抓取流程
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# === 公告管理 ===

@app.route("/admin/announcements")      # 📢 公告列表
def admin_announcements():
    """后台公告列表"""
    db = get_db()
    announcements = db.execute(
        "SELECT * FROM announcements ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return render_template("admin/announcements.html", announcements=announcements)

@app.route("/admin/announcement/new", methods=["GET","POST"])  # ➕ 新建公告
def admin_announcement_new():
    """后台新建公告"""
    if request.method == "POST":
        db = get_db()
        data = request.form
        db.execute(
            "INSERT INTO announcements (title, content_html, is_pinned, status) VALUES (?,?,?,?)",
            (data.get("title"),
             str(sanitize_html(data.get("content_html"))),
             int(data.get("is_pinned",0)),
             data.get("status","published")))
        db.commit(); db.close()
        return redirect("/admin/announcements")
    return render_template("admin/announcement_edit.html", announcement=None)

@app.route("/admin/announcement/<int:aid>", methods=["GET","POST"])  # ✏️ 编辑公告
def admin_announcement_edit(aid):
    """后台编辑公告"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE announcements SET title=?, content_html=?, is_pinned=?, status=? WHERE id=?",
            (data.get("title"),
             str(sanitize_html(data.get("content_html"))),
             int(data.get("is_pinned",0)),
             data.get("status"), aid))
        db.commit(); db.close()
        return redirect("/admin/announcements")
    announcement = db.execute(
        "SELECT * FROM announcements WHERE id=?", (aid,)
    ).fetchone()
    db.close()
    return render_template("admin/announcement_edit.html", announcement=announcement)

# ========== 资产管理后台路由 ==========

# === 仪表盘 ===

@app.route("/admin/assets")
def admin_assets_dashboard():
    """资产管理仪表盘"""
    db = get_db()
    total_codes = db.execute("SELECT COUNT(*) FROM asset_codes").fetchone()[0]
    total_unit_a = db.execute("SELECT COUNT(*) FROM unit_a_assets").fetchone()[0]
    total_unit_b = db.execute("SELECT COUNT(*) FROM unit_b_assets").fetchone()[0]
    total_qty_a = db.execute("SELECT COALESCE(SUM(quantity),0) FROM unit_a_assets").fetchone()[0]
    total_qty_b = db.execute("SELECT COALESCE(SUM(quantity),0) FROM unit_b_assets").fetchone()[0]
    unit_a_by_dept = db.execute(
        "SELECT department, COUNT(*) as cnt, SUM(quantity) as total_qty "
        "FROM unit_a_assets GROUP BY department ORDER BY department"
    ).fetchall()
    unit_a_table_qty = db.execute(
        "SELECT COALESCE(SUM(ua.quantity),0) FROM unit_a_assets ua "
        "JOIN asset_codes ac ON ua.asset_code_id = ac.id WHERE ac.category='table'"
    ).fetchone()[0]
    unit_a_chair_qty = db.execute(
        "SELECT COALESCE(SUM(ua.quantity),0) FROM unit_a_assets ua "
        "JOIN asset_codes ac ON ua.asset_code_id = ac.id WHERE ac.category='chair'"
    ).fetchone()[0]
    unit_b_table_qty = db.execute(
        "SELECT COALESCE(SUM(ub.quantity),0) FROM unit_b_assets ub "
        "JOIN asset_codes ac ON ub.asset_code_id = ac.id WHERE ac.category='table'"
    ).fetchone()[0]
    unit_b_chair_qty = db.execute(
        "SELECT COALESCE(SUM(ub.quantity),0) FROM unit_b_assets ub "
        "JOIN asset_codes ac ON ub.asset_code_id = ac.id WHERE ac.category='chair'"
    ).fetchone()[0]
    db.close()
    return render_template("admin/assets_dashboard.html",
                           stats={"total_codes": total_codes,
                                  "total_unit_a": total_unit_a,
                                  "total_unit_b": total_unit_b,
                                  "total_qty_a": total_qty_a,
                                  "total_qty_b": total_qty_b},
                           unit_a_by_dept=unit_a_by_dept,
                           unit_a_table_qty=unit_a_table_qty,
                           unit_a_chair_qty=unit_a_chair_qty,
                           unit_b_table_qty=unit_b_table_qty,
                           unit_b_chair_qty=unit_b_chair_qty)

# === 资产编码管理 ===

@app.route("/admin/assets/codes")
def admin_asset_codes_list():
    """资产编码列表"""
    db = get_db()
    codes = db.execute(
        "SELECT * FROM asset_codes ORDER BY category, sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/asset_codes.html", codes=codes)

@app.route("/admin/assets/code/new", methods=["GET","POST"])
def admin_asset_code_new():
    """新建资产编码"""
    if request.method == "POST":
        db = get_db()
        data = request.form
        db.execute(
            "INSERT INTO asset_codes (code, name, category, sort_order) VALUES (?,?,?,?)",
            (data.get("code"), data.get("name"), data.get("category"),
             int(data.get("sort_order", 0))))
        db.commit(); db.close()
        return redirect("/admin/assets/codes")
    return render_template("admin/asset_code_edit.html", code=None)

@app.route("/admin/assets/code/<int:code_id>", methods=["GET","POST"])
def admin_asset_code_edit(code_id):
    """编辑资产编码"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE asset_codes SET code=?, name=?, category=?, sort_order=? WHERE id=?",
            (data.get("code"), data.get("name"), data.get("category"),
             int(data.get("sort_order", 0)), code_id))
        db.commit(); db.close()
        return redirect("/admin/assets/codes")
    code = db.execute("SELECT * FROM asset_codes WHERE id=?", (code_id,)).fetchone()
    db.close()
    return render_template("admin/asset_code_edit.html", code=code)

# === 科室管理 ===

@app.route("/admin/assets/departments")
def admin_departments_list():
    """科室列表"""
    db = get_db()
    departments = db.execute(
        "SELECT * FROM asset_departments ORDER BY sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/departments.html", departments=departments)

@app.route("/admin/assets/departments/new", methods=["GET","POST"])
def admin_department_new():
    """新建科室"""
    if request.method == "POST":
        db = get_db()
        data = request.form
        db.execute(
            "INSERT INTO asset_departments (name, sort_order) VALUES (?,?)",
            (data.get("name"), int(data.get("sort_order", 0))))
        db.commit(); db.close()
        return redirect("/admin/assets/departments")
    return render_template("admin/department_edit.html", department=None)

@app.route("/admin/assets/departments/<int:dept_id>", methods=["GET","POST"])
def admin_department_edit(dept_id):
    """编辑科室"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE asset_departments SET name=?, sort_order=? WHERE id=?",
            (data.get("name"), int(data.get("sort_order", 0)), dept_id))
        db.commit(); db.close()
        return redirect("/admin/assets/departments")
    department = db.execute(
        "SELECT * FROM asset_departments WHERE id=?", (dept_id,)
    ).fetchone()
    db.close()
    return render_template("admin/department_edit.html", department=department)

# === 单位A资产管理 ===

@app.route("/admin/assets/unit-a")
def admin_unit_a_list():
    """单位A资产列表（支持按科室筛选）"""
    db = get_db()
    department = request.args.get("department", "")
    if department:
        assets = db.execute(
            "SELECT ua.*, ac.code, ac.name as code_name, ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id = ac.id "
            "WHERE ua.department=? ORDER BY ua.department, ac.category, ac.sort_order",
            (department,)
        ).fetchall()
    else:
        assets = db.execute(
            "SELECT ua.*, ac.code, ac.name as code_name, ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id = ac.id "
            "ORDER BY ua.department, ac.category, ac.sort_order"
        ).fetchall()
    dept_rows = db.execute(
        "SELECT DISTINCT department FROM unit_a_assets ORDER BY department"
    ).fetchall()
    db.close()
    return render_template("admin/unit_a_assets.html",
                           assets=assets,
                           current_department=department,
                           departments=[r["department"] for r in dept_rows])

@app.route("/admin/assets/unit-a/new", methods=["GET","POST"])
def admin_unit_a_new():
    """新建单位A资产"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "INSERT INTO unit_a_assets (department, asset_code_id, quantity, remark) VALUES (?,?,?,?)",
            (data.get("department"), int(data.get("asset_code_id")),
             int(data.get("quantity", 1)), data.get("remark", "")))
        db.commit(); db.close()
        return redirect("/admin/assets/unit-a")
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category, sort_order").fetchall()
    departments = db.execute("SELECT * FROM asset_departments ORDER BY sort_order").fetchall()
    db.close()
    return render_template("admin/unit_a_edit.html", asset=None, codes=codes, departments=departments)

@app.route("/admin/assets/unit-a/<int:asset_id>", methods=["GET","POST"])
def admin_unit_a_edit(asset_id):
    """编辑单位A资产"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE unit_a_assets SET department=?, asset_code_id=?, quantity=?, remark=? WHERE id=?",
            (data.get("department"), int(data.get("asset_code_id")),
             int(data.get("quantity", 1)), data.get("remark", ""), asset_id))
        db.commit(); db.close()
        return redirect("/admin/assets/unit-a")
    asset = db.execute(
        "SELECT * FROM unit_a_assets WHERE id=?", (asset_id,)
    ).fetchone()
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category, sort_order").fetchall()
    departments = db.execute("SELECT * FROM asset_departments ORDER BY sort_order").fetchall()
    db.close()
    return render_template("admin/unit_a_edit.html", asset=asset, codes=codes, departments=departments)

@app.route("/admin/assets/unit-a/delete/<int:asset_id>", methods=["POST"])
def admin_unit_a_delete(asset_id):
    """删除单位A资产"""
    db = get_db()
    db.execute("DELETE FROM unit_a_assets WHERE id=?", (asset_id,))
    db.commit(); db.close()
    return redirect("/admin/assets/unit-a")

# === 单位B资产管理 ===

@app.route("/admin/assets/unit-b")
def admin_unit_b_list():
    """单位B资产列表"""
    db = get_db()
    assets = db.execute(
        "SELECT ub.*, ac.code, ac.name as code_name, ac.category "
        "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id = ac.id "
        "ORDER BY ac.category, ac.sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/unit_b_assets.html", assets=assets)

@app.route("/admin/assets/unit-b/new", methods=["GET","POST"])
def admin_unit_b_new():
    """新建单位B资产"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "INSERT INTO unit_b_assets (asset_code_id, quantity, remark) VALUES (?,?,?)",
            (int(data.get("asset_code_id")), int(data.get("quantity", 1)), data.get("remark", "")))
        db.commit(); db.close()
        return redirect("/admin/assets/unit-b")
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category, sort_order").fetchall()
    db.close()
    return render_template("admin/unit_b_edit.html", asset=None, codes=codes)

@app.route("/admin/assets/unit-b/<int:asset_id>", methods=["GET","POST"])
def admin_unit_b_edit(asset_id):
    """编辑单位B资产"""
    db = get_db()
    if request.method == "POST":
        data = request.form
        db.execute(
            "UPDATE unit_b_assets SET asset_code_id=?, quantity=?, remark=? WHERE id=?",
            (int(data.get("asset_code_id")), int(data.get("quantity", 1)),
             data.get("remark", ""), asset_id))
        db.commit(); db.close()
        return redirect("/admin/assets/unit-b")
    asset = db.execute(
        "SELECT * FROM unit_b_assets WHERE id=?", (asset_id,)
    ).fetchone()
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category, sort_order").fetchall()
    db.close()
    return render_template("admin/unit_b_edit.html", asset=asset, codes=codes)

@app.route("/admin/assets/unit-b/delete/<int:asset_id>", methods=["POST"])
def admin_unit_b_delete(asset_id):
    """删除单位B资产"""
    db = get_db()
    db.execute("DELETE FROM unit_b_assets WHERE id=?", (asset_id,))
    db.commit(); db.close()
    return redirect("/admin/assets/unit-b")

# === 标签打印 ===

@app.route("/admin/assets/labels")
def admin_labels():
    """标签打印页"""
    unit = request.args.get("unit", "A").upper()
    db = get_db()
    if unit == "B":
        labels = db.execute(
            "SELECT ub.*, ac.code, ac.name as code_name, ac.category "
            "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id = ac.id "
            "ORDER BY ac.category, ac.sort_order"
        ).fetchall()
    else:
        labels = db.execute(
            "SELECT ua.*, ac.code, ac.name as code_name, ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id = ac.id "
            "ORDER BY ua.department, ac.category, ac.sort_order"
        ).fetchall()
    db.close()
    return render_template("admin/labels.html", labels=labels, unit=unit)

# ========== 应用入口 ==========

if __name__ == "__main__":              # 🚀 直接运行此文件时（非导入模块）
    init_db()                           # 初始化数据库（创建表 + 种子数据）
    print("Enterprise AI Transformation Platform")
    print("Open http://127.0.0.1:5080")
    app.run(host="0.0.0.0",             # 绑定所有网络接口（局域网可访问）
            port=5080,                  # 监听 5080 端口
            debug=False,                # 关闭调试模式（生产环境）
            threaded=True)              # 开启多线程处理请求
