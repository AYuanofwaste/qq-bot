"""Bilibili MCP Server — download videos, check live streams."""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dl import download_video as _download_video
from dl import extract_bvid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("bilibili-mcp")

server = FastMCP("bilibili-downloader")

logger.info("Bilibili MCP server starting (stderr connected: %s)", not sys.stderr.isatty() and "pipe" or "terminal")


@server.tool()
def download_video(url: str, output_dir: str = None) -> str:
    """Download a Bilibili video by URL or BV number.

    Args:
        url: Bilibili video URL (e.g. https://www.bilibili.com/video/BV1xx...)
             or BV number (e.g. BV1xx...)
        output_dir: Output directory (optional)
    """
    bvid = extract_bvid(url)
    display = bvid or url.split("/")[-1][:20]
    logger.info("Downloading: %s -> %s", display, bvid or url)

    try:
        result = _download_video(url, output_dir)
        logger.info("Download complete: %s", result)
        return result
    except Exception as e:
        msg = str(e)
        if "404" in msg or "Not Found" in msg:
            return f"视频不存在或已被删除"
        if "403" in msg or "Forbidden" in msg:
            return f"视频无法访问（可能是地区限制或会员专享）"
        if "Unavailable" in msg or "unavailable" in msg:
            return f"视频不可用（可能已删除或审核中）"
        if "Private" in msg or "private" in msg:
            return f"这是私密视频，无法下载"
        if "age" in msg.lower() and "restrict" in msg.lower():
            return f"这是年龄限制视频，需要登录 cookies"
        if "login" in msg.lower() or "cookie" in msg.lower():
            return f"需要登录账号，请检查 BILIBILI_COOKIES_FILE 配置"
        return f"下载失败: {msg}"


@server.tool()
def fetch_live_following() -> str:
    """Get list of followed streamers currently live on Bilibili.

    Returns JSON with live streamers (uid, name, title, room_id, online count, etc.).
    Requires valid bilibili_cookies.txt in the bilibili/ directory.
    """
    from live import fetch_live_following as _fetch, COOKIES_FILE as _ck

    try:
        items = _fetch()
    except Exception as e:
        logger.error("fetch_live_following error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if items and isinstance(items[0], dict) and items[0].get("error"):
        err = items[0]["error"]
        if err == "cookies_missing":
            return json.dumps({
                "error": "未配置 B站 cookies，请在 bilibili/ 目录放置 bilibili_cookies.txt"
            }, ensure_ascii=False)
        elif err == "cookies_invalid":
            return json.dumps({
                "error": "B站 cookies 已失效（缺少 DedeUserID），请重新导出"
            }, ensure_ascii=False)
        elif err == "no_follows":
            return json.dumps({"live": [], "message": "你还没有关注任何主播"}, ensure_ascii=False)
        return json.dumps({"error": f"查询失败: {err}"}, ensure_ascii=False)

    return json.dumps({"live": items, "total": len(items)}, ensure_ascii=False, indent=2)


@server.tool()
def search_live(keyword: str, page: int = 1) -> str:
    """Search Bilibili live streams by keyword.

    Args:
        keyword: Search keyword (streamer name, game title, etc.)
        page: Page number (default 1)
    """
    import requests

    try:
        cookies = _load_live_cookies()
        if not cookies:
            return json.dumps({
                "error": "B站搜索需要 cookies，请在 bilibili/ 目录放置 bilibili_cookies.txt"
            }, ensure_ascii=False)

        cs = requests.Session()
        cs.cookies.update(cookies)
        cs.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        })

        resp = cs.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"keyword": keyword, "search_type": "live_room", "page": page, "page_size": 20},
            timeout=15,
        )
        if resp.status_code != 200:
            return json.dumps({"error": f"B站API返回 {resp.status_code}，cookies 可能已过期"}, ensure_ascii=False)
        data = resp.json()
    except Exception as e:
        logger.error("search_live error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if data.get("code") != 0:
        return json.dumps({"error": data.get("message", "搜索失败")}, ensure_ascii=False)

    rooms = []
    result = data.get("data", {}).get("result", {})
    if isinstance(result, list):
        items = result
    else:
        items = result.get("live_room", []) if isinstance(result, dict) else []

    def _abs_url(url: str) -> str:
        return ("https:" + url) if url.startswith("//") else url

    for item in items:
        if not isinstance(item, dict):
            continue
        rooms.append({
            "room_id": item.get("roomid", ""),
            "uid": item.get("uid", ""),
            "name": item.get("uname", ""),
            "title": item.get("title", ""),
            "area": item.get("cate_name", item.get("area_v2_name", "")),
            "online": item.get("online", 0),
            "face": _abs_url(
                item.get("uface") or item.get("upic") or item.get("face") or ""
            ),
            "cover": _abs_url(
                item.get("cover") or item.get("user_cover") or item.get("room_cover")
                or item.get("live_cover") or ""
            ),
            "link": f"https://live.bilibili.com/{item.get('roomid', '')}",
        })

    return json.dumps({
        "keyword": keyword,
        "page": page,
        "rooms": rooms,
    }, ensure_ascii=False, indent=2)


def _load_live_cookies() -> dict[str, str]:
    """Load cookies from bilibili_cookies.txt for API requests."""
    from pathlib import Path
    cookies: dict[str, str] = {}
    for candidate in (
        Path(__file__).resolve().parent / "bilibili_cookies.txt",
        Path(__file__).resolve().parent.parent / "bilibili_cookies.txt",
    ):
        try:
            if candidate.exists():
                with open(candidate, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("\t")
                        if len(parts) >= 7:
                            cookies[parts[5].strip()] = parts[6].strip()
                break
        except Exception:
            pass
    return cookies


@server.tool()
def extract_bvid_url(text: str) -> str:
    """Extract BV number from a Bilibili video URL or short link.

    Args:
        text: URL or text containing a Bilibili link
    """
    bvid = extract_bvid(text)
    if bvid:
        return json.dumps({"bvid": bvid, "url": f"https://www.bilibili.com/video/{bvid}"})
    return json.dumps({"error": "未识别到有效的 B站 BV 号"})


if __name__ == "__main__":
    server.run(transport="stdio")
