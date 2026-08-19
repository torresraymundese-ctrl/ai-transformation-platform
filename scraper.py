#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""企业AI转型平台 — 内容抓取引擎（8源版）"""
import sys, os, requests, re, sqlite3, time, json, hashlib
from datetime import datetime
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from models import get_db

PROXY = {"http": None, "https": None}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

def article_exists(title):
    db = get_db()
    key = hashlib.md5(title.encode()).hexdigest()[:16]
    exists = db.execute("SELECT COUNT(*) FROM articles WHERE title_hash=?", (key,)).fetchone()[0] > 0
    db.close()
    return exists

def save_article(title, source, source_url, summary, tags, category="insight", content_html=""):
    if article_exists(title): return False
    db = get_db()
    key = hashlib.md5(title.encode()).hexdigest()[:16]
    db.execute("INSERT OR IGNORE INTO articles (title_hash,title,source,source_url,summary,content_html,tags,category,publish_date) VALUES (?,?,?,?,?,?,?,?,date('now'))",
               (key, title, source, source_url, summary, content_html, tags, category))
    db.commit(); db.close()
    return True

def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, proxies=PROXY)
        r.encoding = r.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]): tag.decompose()
        content = soup.find("article") or soup.find(class_=re.compile(r"(content|article|post|body|main)", re.I))
        if not content: content = soup.find("body")
        if content:
            text = content.get_text(separator="\n", strip=True)
            if len(text) > 5000: text = text[:5000] + "..."
            paragraphs = [p for p in text.split("\n") if len(p.strip()) > 20]
            return "<p>" + "</p><p>".join(paragraphs[:30]) + "</p>"
    except Exception: pass
    return ""

# ====== TIER 1: 推荐优先抓取 ======

def scrape_synced():
    """机器之心 synced.com — 企业AI案例、行业报告"""
    count = 0
    try:
        r = requests.get("https://synced.com", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "机器", "深度", "报告", "模型", "应用", "落地", "转型"]): continue
            full_url = href if href.startswith("http") else f"https://synced.com{href}"
            summary = title[:160]
            tags = "AI,机器之心"
            if "企业" in title: tags += ",企业AI"
            if "模型" in title: tags += ",大模型"
            content = fetch_article_content(full_url)
            if save_article(title, "机器之心", full_url, summary, tags, "insight", content): count += 1
    except Exception as e: print(f"  Synced error: {e}")
    return count

def scrape_qbitai():
    """量子位 qbitai.com — 大模型、企业级AI转型案例"""
    count = 0
    try:
        r = requests.get("https://www.qbitai.com", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "GPT", "Claude", "机器人", "算法", "生成式", "应用", "落地"]): continue
            full_url = href if href.startswith("http") else f"https://www.qbitai.com{href}"
            summary = title[:160]
            tags = "AI,量子位"
            if "模型" in title: tags += ",大模型"
            if "企业" in title: tags += ",企业AI"
            content = fetch_article_content(full_url)
            if save_article(title, "量子位", full_url, summary, tags, "insight", content): count += 1
    except Exception as e: print(f"  Qbitai error: {e}")
    return count

def scrape_csdn_ai():
    """CSDN 人工智能频道 blog.csdn.net — 企业AI实践、架构、技术科普"""
    count = 0
    try:
        urls = [
            "https://blog.csdn.net/nav/ai",
            "https://blog.csdn.net/nav/langchain"
        ]
        for base in urls:
            r = requests.get(base, headers=HEADERS, timeout=15, proxies=PROXY)
            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a[href]")
            for link in links:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if not title or not href or len(title) < 12: continue
                if not any(k in title for k in ["AI", "智能", "大模型", "RAG", "企业", "Transformer", "Agent", "部署", "知识库", "深度学习"]): continue
                full_url = href if href.startswith("http") else f"https://blog.csdn.net{href}" if not href.startswith("/") else href
                if "blog.csdn.net" not in full_url: continue
                summary = title[:160]
                tags = "AI,CSDN,技术"
                if "RAG" in title.upper() or "知识库" in title: tags += ",RAG,知识库"
                if "Agent" in title: tags += ",Agent,智能体"
                content = fetch_article_content(full_url)
                if save_article(title, "CSDN", full_url, summary, tags, "tech", content): count += 1
    except Exception as e: print(f"  CSDN error: {e}")
    return count

def scrape_aliyun_dev():
    """阿里云开发者社区 developer.aliyun.com — 传统行业+AI转型实战"""
    count = 0
    try:
        r = requests.get("https://developer.aliyun.com/article", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "转型", "RAG", "Agent", "数字化", "机器学习", "深度学习", "模型"]): continue
            full_url = href if href.startswith("http") else f"https://developer.aliyun.com{href}"
            summary = title[:160]
            tags = "AI,阿里云,企业AI"
            if "模型" in title: tags += ",大模型"
            if "RAG" in title.upper(): tags += ",RAG"
            content = fetch_article_content(full_url)
            if save_article(title, "阿里云开发者", full_url, summary, tags, "tech", content): count += 1
    except Exception as e: print(f"  Aliyun Dev error: {e}")
    return count

def scrape_huawei_dev():
    """华为云开发者 developer.huaweicloud.com — 企业开源、硬件转型案例"""
    count = 0
    try:
        r = requests.get("https://developer.huaweicloud.com/develop/aigallery/home.html", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "鲲鹏", "昇腾", "深度学习", "部署", "模型", "MindSpore", "RAG"]): continue
            full_url = href if href.startswith("http") else f"https://developer.huaweicloud.com{href}"
            summary = title[:160]
            tags = "AI,华为云"
            if "模型" in title: tags += ",大模型"
            if "RAG" in title.upper(): tags += ",RAG"
            content = fetch_article_content(full_url)
            if save_article(title, "华为云开发者", full_url, summary, tags, "tech", content): count += 1
    except Exception as e: print(f"  Huawei Dev error: {e}")
    return count

# ====== TIER 2: 需额外投入（JS渲染/反爬） ======

def scrape_aiera():
    """AI Era aiera.cn — 优质AI内容，需浏览器渲染"""
    count = 0
    try:
        r = requests.get("https://aiera.cn", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "Agent", "RAG", "深度学习", "模型", "应用"]): continue
            full_url = href if href.startswith("http") else f"https://aiera.cn{href}"
            summary = title[:160]
            tags = "AI,AIEra,行业"
            if "Agent" in title: tags += ",Agent"
            content = fetch_article_content(full_url)
            if save_article(title, "AI Era", full_url, summary, tags, "insight", content): count += 1
    except Exception as e: print(f"  AI Era error: {e}")
    return count

def scrape_36kr_ai():
    """36氪 AI频道 36kr.com — 资讯密集，企业AI投融资"""
    count = 0
    try:
        r = requests.get("https://36kr.com/search/articles/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "融资", "Agent", "数字化", "转型", "人工智能", "应用"]): continue
            full_url = href if href.startswith("http") else f"https://36kr.com{href}"
            summary = title[:160]
            tags = "AI,36氪,动态"
            content = fetch_article_content(full_url)
            if save_article(title, "36氪", full_url, summary, tags, "insight", content): count += 1
    except Exception as e: print(f"  36Kr error: {e}")
    return count

def scrape_infoq():
    """InfoQ infoq.cn — 架构/白皮书级内容，企业AI落地"""
    count = 0
    try:
        r = requests.get("https://www.infoq.cn/topic/ai", headers=HEADERS, timeout=15, proxies=PROXY)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select("a[href]")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href or len(title) < 12: continue
            if not any(k in title for k in ["AI", "智能", "大模型", "企业", "架构", "转型", "RAG", "Agent", "数字化", "人工智能"]): continue
            full_url = href if href.startswith("http") else f"https://www.infoq.cn{href}"
            summary = title[:160]
            tags = "AI,InfoQ,架构"
            if "架构" in title: tags += ",架构"
            content = fetch_article_content(full_url)
            if save_article(title, "InfoQ", full_url, summary, tags, "whitepaper", content): count += 1
    except Exception as e: print(f"  InfoQ error: {e}")
    return count

# ====== 平台原创精选 ======

def add_curated_articles():
    curated = [
        {"title":"企业RAG知识库落地指南：从数据治理到智能问答","source":"企业AI转型平台原创","source_url":"","summary":"RAG（检索增强生成）是企业AI转型的最佳起点。本文详细拆解了从数据清洗、文档向量化到智能问答的全流程，包含制造业和金融业的真实案例。","tags":"RAG,知识库,企业AI,入门指南","category":"tech","content":"<p>RAG（Retrieval-Augmented Generation）是当下企业 AI 落地最成熟、性价比最高的场景。</p><p>核心流程分为三步：<strong>1. 数据治理</strong>——清洗、标准化企业文档；<strong>2. 向量化</strong>——将文档转为机器可检索的向量；<strong>3. 检索生成</strong>——用户提问时先检索相关文档再交给大模型作答。</p>"},
        {"title":"为什么企业AI转型必须从本地大模型开始","source":"企业AI转型平台原创","source_url":"","summary":"数据安全是企业AI转型的第一关。本文对比了公有云API和本地私有化部署的优劣，解释了为什么金融、医疗、制造业必须选择本地部署方案。","tags":"大模型,私有部署,数据安全,Qwen","category":"tech","content":"<p>企业选择 AI 方案时，数据安全是第一考量。公有云 API 虽然方便，但数据传输到外部服务器，无法满足金融、医疗等强监管行业的合规要求。</p><p>本地部署方案使用开源模型（如 Qwen2.5、DeepSeek、GLM），数据完全不出内网。配合 4-bit 量化技术，一台 RTX 4060 即可流畅运行 7B 参数的模型。</p>"},
        {"title":"麦肯锡2025 AI报告：企业AI转型的五大关键发现","source":"McKinsey & Company","source_url":"https://www.mckinsey.com/capabilities/quantumblack/our-insights","summary":"麦肯锡最新报告指出：1) AI 应用率从2023年的55%跃升至2025年的78%；2) RAG 是最广泛落地的AI场景；3) 数据质量仍是最大瓶颈；4) AI 人才缺口持续扩大；5) 生成式AI 投资回报开始显现。","tags":"AI转型,行业报告,McKinsey,趋势","category":"whitepaper","content":""},
        {"title":"工信部：中小企业数字化转型指南解读","source":"工信部赛迪研究院","source_url":"","summary":"工信部发布的最新中小企业数字化转型指南明确指出：中小企业应优先从低门槛AI应用场景入手，RAG知识库和智能客服是推荐的首选方向。政府将对AI转型项目提供专项补贴。","tags":"政策,数字化转型,中小企业","category":"whitepaper"},
        {"title":"AI智能体(Agent)如何改变企业工作流","source":"企业AI转型平台原创","source_url":"","summary":"AI智能体不只是聊天——它可以自动调用ERP系统、查询数据库、生成报表、推送审批提醒。本文介绍企业如何从RAG升级到Agent，实现真正的业务流程自动化。","tags":"Agent,智能体,流程自动化,RPA","category":"tech","content":"<p>AI Agent 是 RAG 的自然升级。RAG 解决[知道什么]的问题，Agent 解决[做什么]的问题。</p><p>企业 Agent 的核心能力包括：<strong>工具调用</strong>、<strong>流程编排</strong>、<strong>记忆管理</strong>。</p><p>典型场景：财务 Agent 自动生成月度报表并邮件发送，人力 Agent 自动筛选简历并安排面试。</p>"},
        {"title":"垂直行业RAG为什么比通用方案值钱10倍","source":"企业AI转型平台原创","source_url":"","summary":"通用RAG方案在制造业、医疗、金融等行业往往水土不服。行业垂直RAG需要处理专业术语、特殊文档格式和严格的合规要求。本文拆解四个行业的定制化RAG方案。","tags":"RAG,垂直行业,制造,医疗,金融","category":"insight"},
        {"title":"企业AI转型成本分析：从入门到高阶的投入对比","source":"企业AI转型平台原创","source_url":"","summary":"企业AI转型到底要花多少钱？本文详细对比了三种投入方案：启航包（10万以内）、加速包（10-50万）、旗舰包（50-200万），包含硬件、软件、人力、运维的完整成本拆解。","tags":"成本,投入,AI转型,定价","category":"insight"},
        {"title":"Qwen2.5 vs DeepSeek vs GLM：企业本地大模型选型指南","source":"企业AI转型平台原创","source_url":"","summary":"三款主流国产开源大模型全面对比：中文理解能力、推理速度、硬件需求、部署难度、社区活跃度。帮助企业根据自身场景选择最合适的模型。","tags":"大模型,Qwen,DeepSeek,GLM,选型","category":"tech"},
    ]
    count = 0
    for item in curated:
        if save_article(item["title"], item["source"], item["source_url"], item["summary"], item["tags"], item["category"], item.get("content", "")): count += 1
    return count

# ====== 入口 ======

def run_scraper():
    print(f"[{datetime.now():%H:%M:%S}] 开始内容抓取...")
    total = 0
    # Tier 1: 推荐优先
    total += scrape_synced()          # 机器之心
    total += scrape_qbitai()          # 量子位
    total += scrape_csdn_ai()         # CSDN AI频道
    total += scrape_aliyun_dev()      # 阿里云开发者
    total += scrape_huawei_dev()      # 华为云开发者
    # Tier 2: 尽力抓取
    total += scrape_aiera()           # AI Era
    total += scrape_36kr_ai()         # 36氪 AI
    total += scrape_infoq()           # InfoQ
    # 原创精选
    total += add_curated_articles()
    print(f"[{datetime.now():%H:%M:%S}] 完成。新增 {total} 篇文章。")
    return total

if __name__ == "__main__":
    print("Content Scraper for Enterprise AI Transformation Platform")
    print("=" * 50)
    run_scraper()
