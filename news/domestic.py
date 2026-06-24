import logging
from datetime import date

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("game_news")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _fetch_ali213(max_items: int = 5) -> list[dict]:
    url = "https://www.ali213.net/news/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    seen_links = set()

    for blocks_div in soup.find_all("div", class_="blocks"):
        for a in blocks_div.find_all("a", href=True):
            if "news/html/" not in a["href"]:
                continue
            if a["href"] in seen_links:
                continue

            img = a.find("img")
            if not img:
                continue
            title = a.get("title") or a.get_text(strip=True)
            if not title or len(title) < 8:
                continue

            src = img.get("data-original") or img.get("src", "")
            if not src:
                continue

            seen_links.add(a["href"])
            items.append({"title": title, "link": a["href"], "img": src})
            if len(items) >= max_items:
                break

        if len(items) >= max_items:
            break

    return items


def fetch_news() -> str:
    """国内游戏新闻（ali213 最新 5 条，带图）。"""
    try:
        items = _fetch_ali213(5)
    except Exception as e:
        logger.error("Failed to fetch game news: %s", e)
        return f"❌ 获取游戏新闻失败: {e}"

    if not items:
        return "❌ 暂时拿不到国内游戏新闻"

    lines = [f"【国内游戏新闻】（最新 {len(items)} 条）"]
    for i, item in enumerate(items, 1):
        title = item["title"][:60]
        img_cq = f"[CQ:image,file={item['img']}]" if item["img"] else ""
        lines.append(f"{img_cq}\n{i}. {title}\n   🔗 {item['link']}")

    return "\n\n".join(lines)
