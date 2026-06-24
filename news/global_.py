"""国外游戏热料聚合模块 —— VGC / ResetEra / Insider Gaming / Steam 即将发售 / Bluesky 记者。

数据源:
  1. VGC RSS —— 主力英文游戏新闻
  2. ResetEra RSS —— 论坛爆料帖过滤（带来源标签或 EXCLUSIVE/RUMOR/LEAK 关键词）
  3. Insider Gaming RSS —— Tom Henderson 等独家爆料
  4. Steam 即将发售 —— 抓商店搜索页 HTML
  5. Bluesky —— 监控爆料记者账号时间线（公共 API，无需 token）

英文标题+摘要由 DeepSeek 批量翻译成中文，带进程内缓存。
"""

import hashlib
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

logger = logging.getLogger("game_global")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ── 数据源配置 ────────────────────────────────────────────────────
VGC_FEED = "https://www.videogameschronicle.com/feed/"
RESETERA_FEED = "https://www.resetera.com/forums/gaming-forum.7/index.rss"
INSIDER_FEED = "https://insider-gaming.com/feed/"
STEAM_SEARCH_URL = "https://store.steampowered.com/search/"
BLUESKY_API = "https://public.api.bsky.app/xrpc"

# Bluesky 监控的记者/官方账号 (handle → did)
BLUESKY_REPORTERS = {
    "insider-gaming.com": "did:plc:ydes4m2jwf7vjoygesyaqxoy",
}

# ResetEra 爆料帖过滤关键词（大小写不敏感）
LEAK_KEYWORDS = re.compile(
    r"(?:exclusive|rumor|rumour|leak|report|breaking|reveal|announce|"
    r"sources?|according to|suggests?|plans?|working on|delays?|cancelled)",
    re.IGNORECASE,
)
# 标题前缀标签形如 [Tom Henderson] [TheVerge] [IGN]
SOURCE_TAG_RE = re.compile(r"^\[.+?\]")


# ── RSS 通用解析 ──────────────────────────────────────────────────
def _parse_rss(xml_text: str, max_items: int = 10) -> list[dict]:
    """解析 RSS 2.0 feed，返回 [{title, link, description, pub_date, image, comments}]。"""
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item in soup.find_all("item")[:max_items]:
        title = item.find("title")
        link = item.find("link")
        desc = item.find("description")
        pub = item.find("pubDate")
        comments = item.find("slash:comments") or item.find("comments")
        # 缩略图：从 description 的 <img src> 提取，或 media:content/media:thumbnail
        img = ""
        if desc:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc.get_text() or str(desc))
            if m:
                img = m.group(1)
        if not img:
            mc = item.find("media:content") or item.find("media:thumbnail")
            if mc:
                img = mc.get("url", "")
        items.append({
            "title": title.get_text(strip=True) if title else "",
            "link": link.get_text(strip=True) if link else "",
            "description": _strip_html(desc.get_text(strip=True) if desc else "")[:200],
            "pub_date": _parse_date(pub.get_text(strip=True) if pub else ""),
            "image": img,
            "comments": int(comments.get_text(strip=True)) if comments and comments.get_text(strip=True).isdigit() else 0,
        })
    return items


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_date(s: str) -> str:
    """RFC822 日期 → ISO YYYY-MM-DD HH:MM。失败返回原字符串。"""
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


# ── 各源抓取函数 ──────────────────────────────────────────────────
def _fetch_vgc(max_items: int = 5) -> list[dict]:
    try:
        r = requests.get(VGC_FEED, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logger.warning("VGC status %s", r.status_code)
            return []
        items = _parse_rss(r.text, max_items)
        for it in items:
            it["source"] = "VGC"
            it["source_icon"] = "🌐"
        return items
    except Exception as e:
        logger.warning("VGC error: %s", e)
        return []


def _fetch_insider_gaming(max_items: int = 5) -> list[dict]:
    try:
        r = requests.get(INSIDER_FEED, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logger.warning("Insider Gaming status %s", r.status_code)
            return []
        items = _parse_rss(r.text, max_items)
        for it in items:
            it["source"] = "Insider Gaming"
            it["source_icon"] = "🕵"
        return items
    except Exception as e:
        logger.warning("Insider Gaming error: %s", e)
        return []


def _fetch_resetera_leaks(max_items: int = 5, min_comments: int = 20) -> list[dict]:
    try:
        r = requests.get(RESETERA_FEED, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logger.warning("ResetEra status %s", r.status_code)
            return []
        all_items = _parse_rss(r.text, 50)
        leaks = []
        for it in all_items:
            title = it["title"]
            is_leak = bool(SOURCE_TAG_RE.match(title)) or bool(LEAK_KEYWORDS.search(title))
            if not is_leak:
                continue
            if it["comments"] and it["comments"] < min_comments:
                continue
            it["source"] = "ResetEra"
            it["source_icon"] = "🗣"
            leaks.append(it)
            if len(leaks) >= max_items:
                break
        return leaks
    except Exception as e:
        logger.warning("ResetEra error: %s", e)
        return []


def _fetch_steam_comingsoon(max_items: int = 5) -> list[dict]:
    """抓 Steam 即将发售，返回前 max_items 条。"""
    try:
        r = requests.get(
            STEAM_SEARCH_URL,
            params={"filter": "comingsoon", "l": "schinese", "page": "1"},
            headers=HEADERS, timeout=20,
        )
        if r.status_code != 200:
            logger.warning("Steam status %s", r.status_code)
            return []
        r.encoding = "utf-8"
        entries = re.findall(
            r'<a[^>]*data-ds-appid="(\d+)"[^>]*>(.*?)</a>',
            r.text, re.S,
        )
        items = []
        for appid, body in entries:
            m_name = re.search(r'<span class="title[^"]*"[^>]*>(.*?)</span>', body, re.S)
            m_date = re.search(
                r'class="col search_released[^"]*"[^>]*>\s*(.*?)\s*</div>',
                body, re.S,
            )
            m_img = re.search(r'src="([^"]*capsule[^"]*)"', body)
            name = _strip_html(m_name.group(1)) if m_name else ""
            date = _strip_html(m_date.group(1)) if m_date else "即将推出"
            img = m_img.group(1) if m_img else ""
            if not name:
                continue
            items.append({
                "title": name,
                "link": f"https://store.steampowered.com/app/{appid}/",
                "description": date,
                "pub_date": "",
                "image": img,
                "comments": 0,
                "source": "Steam",
                "source_icon": "🎮",
                "need_translate": False,
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        logger.warning("Steam error: %s", e)
        return []


def _fetch_bluesky_reporters(max_items: int = 5) -> list[dict]:
    """抓取 Bluesky 监控账号的最新帖子。"""
    items = []
    for handle, did in BLUESKY_REPORTERS.items():
        try:
            r = requests.get(
                f"{BLUESKY_API}/app.bsky.feed.getAuthorFeed",
                params={"actor": did, "limit": max_items, "filter": "posts_no_replies"},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            if r.status_code != 200:
                logger.warning("Bluesky %s status %s", handle, r.status_code)
                continue
            feed = r.json().get("feed", [])
            for entry in feed:
                post = entry.get("post", {})
                record = post.get("record", {})
                text = record.get("text", "")
                if not text:
                    continue
                # 提取文本里的链接
                link = ""
                for facet in record.get("facets", []):
                    for feat in facet.get("features", []):
                        if feat.get("$type") == "app.bsky.richtext.facet#link":
                            link = feat.get("uri", "")
                            break
                    if link:
                        break
                if not link:
                    # 用帖子 URI 构造 web 链接
                    uri = post.get("uri", "")
                    if uri.startswith("at://"):
                        parts = uri.split("/")
                        if len(parts) >= 4:
                            link = f"https://bsky.app/profile/{handle}/post/{parts[-1]}"
                created = record.get("createdAt", "")
                pub = ""
                if created:
                    try:
                        pub = datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pub = created
                # 截断长文，第一行作标题，其余作摘要
                lines = text.split("\n", 1)
                title = lines[0][:120]
                desc = lines[1].strip()[:200] if len(lines) > 1 else ""
                # 去掉摘要里残留的 URL 片段（Bluesky 把链接内联到 text 里）
                desc = re.sub(r"https?://\S+", "", desc).strip()
                desc = re.sub(r"[a-z0-9-]+\.(?:com|net|org)/\S*", "", desc).strip()
                if not desc or len(desc) < 8:
                    desc = ""
                items.append({
                    "title": title,
                    "link": link,
                    "description": desc,
                    "pub_date": pub,
                    "image": "",
                    "comments": 0,
                    "source": f"Bluesky @{handle}",
                    "source_icon": "🦋",
                })
            if len(items) >= max_items:
                break
        except Exception as e:
            logger.warning("Bluesky %s error: %s", handle, e)
    return items[:max_items]


# ── DeepSeek 批量翻译 ─────────────────────────────────────────────
_translate_cache: dict[str, str] = {}
_translate_client = None


def _get_translate_client() -> OpenAI:
    global _translate_client
    if _translate_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY 未设置，无法翻译")
        kwargs = {"api_key": api_key}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        _translate_client = OpenAI(**kwargs)
    return _translate_client


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _translate_batch(texts: list[str]) -> list[str]:
    """批量翻译英文文本到中文。带进程内缓存。空字符串直接返回空。"""
    if not texts:
        return []
    # 拆出需要翻译的
    results = [""] * len(texts)
    pending_idx = []
    pending_texts = []
    for i, t in enumerate(texts):
        if not t or not re.search(r"[A-Za-z]{3,}", t):
            results[i] = t
            continue
        key = _cache_key(t)
        if key in _translate_cache:
            results[i] = _translate_cache[key]
            continue
        pending_idx.append(i)
        pending_texts.append(t)

    if not pending_texts:
        return results

    client = _get_translate_client()
    model = os.environ.get("OPENAI_MODEL", "deepseek-chat")
    # 一次性批量翻译，用编号列表
    numbered = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(pending_texts))
    prompt = (
        "你是游戏新闻翻译助手。把下面若干条英文游戏新闻标题或摘要翻译成简洁中文，"
        "保留游戏名、人名、公司名原文（如 Final Fantasy 保留为 Final Fantasy）。"
        "每条用 [编号] 中文翻译 的格式输出，编号要和输入对应，不要添加任何解释或多余行：\n\n"
        + numbered
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是专业的游戏新闻翻译，输出严格按编号格式。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            timeout=30,
        )
        out = resp.choices[0].message.content or ""
        # 解析 [1] xxx [2] yyy
        for m in re.finditer(r"\[(\d+)\]\s*(.+?)(?=\n\[\d+\]|$)", out, re.S):
            num = int(m.group(1))
            translation = m.group(2).strip()
            if 1 <= num <= len(pending_texts):
                idx = pending_idx[num - 1]
                results[idx] = translation
                _translate_cache[_cache_key(pending_texts[num - 1])] = translation
        # 兜底：没匹配上的保留原文
        for j, idx in enumerate(pending_idx):
            if not results[idx]:
                results[idx] = pending_texts[j]
    except Exception as e:
        logger.warning("translate batch failed: %s", e)
        for j, idx in enumerate(pending_idx):
            results[idx] = pending_texts[j]
    return results


# ── 单源格式化（每源取最新 5 条，带图）────────────────────────────
def _format_source(items: list[dict], source_name: str, icon: str,
                   need_translate: bool = True) -> str:
    """把单源 5 条格式化为带 [CQ:image] 的文本。"""
    if not items:
        return f"{icon} {source_name}\n  暂时拿不到，稍后再试"

    # 批量翻译标题和摘要
    if need_translate:
        titles_zh = _translate_batch([it["title"] for it in items])
        descs_zh = _translate_batch([it["description"] for it in items])
    else:
        titles_zh = [it["title"] for it in items]
        descs_zh = [it["description"] for it in items]

    lines = [f"{icon} {source_name}（最新 {len(items)} 条）"]
    for i, it in enumerate(items, 1):
        title = titles_zh[i - 1] if i - 1 < len(titles_zh) else it["title"]
        desc = descs_zh[i - 1] if i - 1 < len(descs_zh) else it["description"]
        pub = it.get("pub_date", "")
        pub_str = f"  ({pub})" if pub else ""
        # Steam 显示发行商
        publisher_tag = f"  [{it['publisher']}]" if it.get("publisher") else ""
        # 图片（CQ 码）
        if it.get("image"):
            lines.append(f"[CQ:image,file={it['image']}]")
        lines.append(f"{i}. {title}{publisher_tag}{pub_str}")
        if desc and desc != title:
            lines.append(f"   {desc[:80]}")
        if it.get("link"):
            lines.append(f"   🔗 {it['link']}")
    return "\n".join(lines)


def fetch_vgc_news() -> str:
    return _format_source(_fetch_vgc(5), "VGC", "🌐", need_translate=True)


def fetch_resetera_news() -> str:
    return _format_source(_fetch_resetera_leaks(5), "ResetEra 爆料", "🗣", need_translate=True)


def fetch_insider_news() -> str:
    """Insider Gaming RSS + Bluesky 合并（按时间排序取前 5）。"""
    rss = _fetch_insider_gaming(5)
    bs = _fetch_bluesky_reporters(5)
    # 用 link 去重（Bluesky 的 link 就是 Insider Gaming 文章链接）
    seen = {it["link"] for it in rss if it.get("link")}
    merged = list(rss)
    for it in bs:
        if it.get("link") and it["link"] in seen:
            continue
        merged.append(it)
    # 按时间倒序
    merged.sort(key=lambda x: x.get("pub_date", ""), reverse=True)
    return _format_source(merged[:5], "Insider Gaming", "🕵", need_translate=True)


def fetch_steam_news() -> str:
    return _format_source(_fetch_steam_comingsoon(5), "Steam 即将发售", "🎮", need_translate=False)


# 源命令调度表
SOURCE_COMMANDS: dict[str, callable] = {
    "vgc": fetch_vgc_news,
    "resetera": fetch_resetera_news,
    "insider": fetch_insider_news,
    "steam": fetch_steam_news,
}


def fetch_global_news() -> str:
    """聚合所有国外源（保留兼容，但不被 /gnews 路由用到了）。"""
    parts = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_vgc_news): "VGC",
            pool.submit(fetch_resetera_news): "ResetEra",
            pool.submit(fetch_insider_news): "Insider",
            pool.submit(fetch_steam_news): "Steam",
        }
        for fut in as_completed(futures):
            try:
                parts.append(fut.result())
            except Exception as e:
                logger.warning("aggregate error: %s", e)
    return "\n\n".join(parts) if parts else "❌ 暂时拿不到任何国外热料"
