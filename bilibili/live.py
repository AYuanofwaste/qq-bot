"""查询 B站我关注的主播中正在直播的人。

由于直播页的「关注直播」接口已下线，这里采用两步法：
  1. 通过主站 relation/followings 翻页拿到全部关注 uid
  2. 用 room/v1/Room/get_status_info_by_uids 批量查询直播状态
最后筛出 live_status == 1（直播中）的主播。
"""

import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger("bilibili_live")

COOKIES_FILE = Path(__file__).resolve().parent / "bilibili_cookies.txt"
BACKUP_COOKIES = Path(__file__).resolve().parent.parent / "bilibili_cookies.txt"
if not COOKIES_FILE.exists() and BACKUP_COOKIES.exists():
    COOKIES_FILE = BACKUP_COOKIES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://live.bilibili.com/",
}

FOLLOWINGS_URL = "https://api.bilibili.com/x/relation/followings"
LIVE_STATUS_URL = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"

PAGE_SIZE = 50
BATCH_SIZE = 100
MAX_FOLLOW_PAGES = 200  # 安全上限，足够覆盖 1w 关注


def _load_cookies() -> dict[str, str]:
    cookies: dict[str, str] = {}
    try:
        with open(COOKIES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies[parts[5].strip()] = parts[6].strip()
    except FileNotFoundError:
        logger.error("bilibili cookies 文件不存在: %s", COOKIES_FILE)
    except Exception as e:
        logger.error("读取 bilibili cookies 失败: %s", e)
    return cookies


def _self_uid(cookies: dict[str, str]) -> str | None:
    return cookies.get("DedeUserID")


def _fetch_all_following_uids(cookies: dict[str, str]) -> list[int]:
    uid = _self_uid(cookies)
    if not uid:
        logger.error("cookies 中缺少 DedeUserID，无法查询关注列表")
        return []

    mids: list[int] = []
    headers = {**HEADERS, "Referer": "https://www.bilibili.com/"}
    for pn in range(1, MAX_FOLLOW_PAGES + 1):
        try:
            resp = requests.get(
                FOLLOWINGS_URL,
                headers=headers,
                cookies=cookies,
                params={"vmid": uid, "pn": pn, "ps": PAGE_SIZE, "order": "attention"},
                timeout=15,
            )
            data = resp.json()
        except Exception as e:
            logger.warning("followings page %d failed: %s", pn, e)
            break

        if data.get("code") != 0:
            logger.warning("followings page %d error: %s %s", pn, data.get("code"), data.get("message"))
            break

        lst = data.get("data", {}).get("list", [])
        if not lst:
            break
        mids += [u["mid"] for u in lst if u.get("mid")]
        if len(lst) < PAGE_SIZE:
            break
        time.sleep(0.2)
    return mids


def _batch_live_status(mids: list[int], cookies: dict[str, str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for i in range(0, len(mids), BATCH_SIZE):
        chunk = mids[i:i + BATCH_SIZE]
        params = [("uids[]", str(m)) for m in chunk]
        try:
            resp = requests.get(LIVE_STATUS_URL, headers=HEADERS, params=params, cookies=cookies, timeout=20)
            data = resp.json()
        except Exception as e:
            logger.warning("live status batch %d failed: %s", i, e)
            continue
        if data.get("code") != 0:
            logger.warning("live status batch %d error: %s", i, data.get("message"))
            continue
        for uid, info in (data.get("data") or {}).items():
            result[uid] = info
        time.sleep(0.2)
    return result


def fetch_live_following() -> list[dict]:
    """返回正在直播的关注主播列表。返回空列表表示无人直播。

    失败时返回带特殊键的 dict 列表，调用方可据此区分原因。
    实际为方便 bot.py 调用，失败时返回 list[dict]，其中 dict 含 "error" 键。
    """
    cookies = _load_cookies()
    if not cookies:
        logger.error("未加载到 bilibili cookies")
        return [{"error": "cookies_missing"}]

    uid = _self_uid(cookies)
    if not uid:
        logger.error("cookies 中缺少 DedeUserID，无法查询关注列表")
        return [{"error": "cookies_invalid"}]

    mids = _fetch_all_following_uids(cookies)
    if not mids:
        return [{"error": "no_follows"}]
    logger.info("关注总数 %d，开始批量查询直播状态", len(mids))

    statuses = _batch_live_status(mids, cookies)

    result: list[dict] = []
    for info in statuses.values():
        if info.get("live_status") != 1:
            continue
        room_id = info.get("room_id", 0)
        result.append({
            "uid": info.get("uid", 0),
            "name": info.get("uname", ""),
            "face": info.get("face", ""),
            "room_id": room_id,
            "title": info.get("title", ""),
            "cover": info.get("cover_from_user", ""),
            "area": info.get("area_v2_name", ""),
            "parent_area": info.get("area_v2_parent_name", ""),
            "online": info.get("online", 0),
            "live_time": info.get("live_time", ""),
            "link": f"https://live.bilibili.com/{room_id}",
        })

    result.sort(key=lambda x: x["online"], reverse=True)
    return result


def format_live_list(items: list[dict]) -> str:
    """全量列表（调试用，bot 不再使用）。"""
    if not items:
        return "😴 你关注的主播当前没有人在直播"
    lines = [f"🎮 你关注的主播正在直播 ({len(items)} 人)"]
    for i, item in enumerate(items, 1):
        img = f"[CQ:image,file={item['face']}]" if item.get("face") else ""
        lines.append(
            f"{img}\n"
            f"{i}. {item['name']}\n"
            f"   📺 {item['title'][:40]}\n"
            f"   🏷️ {item['parent_area']} - {item['area']}\n"
            f"   👥 {item['online']} 人观看\n"
            f"   🔗 {item['link']}"
        )
    return "\n\n".join(lines)


def format_live_page(items: list[dict], page: int, page_size: int = 10) -> str:
    """格式化第 page 页（0-indexed），返回带页码与导航提示的单页消息。"""
    total = len(items)
    if total == 0:
        return "😴 你关注的主播当前没有人在直播"
    total_pages = (total + page_size - 1) // page_size
    if page < 0:
        page = 0
    if page > total_pages - 1:
        page = total_pages - 1
    start = page * page_size
    chunk = items[start:start + page_size]

    lines = [f"🎮 关注主播直播中 (共 {total} 人)  [第 {page + 1}/{total_pages} 页]"]
    for i, item in enumerate(chunk, start + 1):
        img = f"[CQ:image,file={item['face']}]" if item.get("face") else ""
        cover = f"[CQ:image,file={item['cover']}]" if item.get("cover") else ""
        lines.append(
            f"{img}\n"
            f"{i}. {item['name']}\n"
            f"   📺 {item['title'][:40]}\n"
            f"{cover}\n"
            f"   🏷️ {item['parent_area']} - {item['area']}\n"
            f"   👥 {item['online']} 人观看\n"
            f"   🔗 {item['link']}"
        )
    nav = []
    if page < total_pages - 1:
        nav.append("/下一页 看更多")
    if page > 0:
        nav.append("/上一页 返回")
    nav.append("/第N页 跳页")
    nav.append("/break 退出")
    lines.append("\n📖 " + " | ".join(nav))
    return "\n\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    items = fetch_live_following()
    print(f"Found {len(items)} live streamers")
    for item in items:
        print(f"  {item['name']} - {item['title'][:30]} - room {item['room_id']} - online {item['online']}")


if __name__ == "__main__":
    main()
