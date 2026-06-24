"""Pixiv MCP Server — search, browse, download illustrations from Pixiv."""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from auth import get_refresh_token, get_phpsessid
from client import PixivService
from downloader import get_manager, detect_ffmpeg, DownloadManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("pixiv-mcp")

server = FastMCP("pixiv-downloader")

# ── Lazy initialisation ──────────────────────────────────────────

_pixiv: PixivService | None = None
_downloader: DownloadManager | None = None


def pixiv() -> PixivService:
    global _pixiv
    if _pixiv is None:
        _pixiv = PixivService()
    return _pixiv


def downloader() -> DownloadManager:
    global _downloader
    if _downloader is None:
        _downloader = get_manager()
    return _downloader


# ── Helper ────────────────────────────────────────────────────────

def _summarise_illust(illust: dict) -> dict:
    """Return a concise summary dict for an illust."""
    user = illust.get("user", {})
    tags = illust.get("tags", [])
    tag_names = []
    for t in tags:
        if isinstance(t, dict):
            tag_names.append(t.get("name", ""))
        elif isinstance(t, str):
            tag_names.append(t)

    return {
        "id": illust.get("id"),
        "title": illust.get("title", ""),
        "type": illust.get("type", "illust"),
        "page_count": illust.get("page_count", 1),
        "user_id": user.get("id"),
        "user_name": user.get("name", ""),
        "tags": tag_names[:10],
        "width": illust.get("width"),
        "height": illust.get("height"),
        "total_bookmarks": illust.get("total_bookmarks", 0),
        "total_view": illust.get("total_view", 0),
        "create_date": illust.get("create_date", ""),
        "image_url": (illust.get("image_urls") or {}).get("medium", ""),
    }


def _extract_illusts(result: dict) -> list[dict]:
    """Extract illust list from API response."""
    if isinstance(result, dict) and "illusts" in result:
        return result["illusts"]
    if isinstance(result, dict) and "illust" in result:
        return [result["illust"]]
    return []


# ── Tools ─────────────────────────────────────────────────────────

@server.tool()
def search_illust(
    word: str,
    search_target: str = "partial_match_for_tags",
    sort: str = "date_desc",
    duration: str | None = None,
    offset: int | None = None,
) -> str:
    """Search illustrations on Pixiv by keyword.

    Args:
        word: Search keyword or tag
        search_target: Search target type. Options:
            partial_match_for_tags (default), exact_match_for_tags,
            title_and_caption, keyword
        sort: Sort order. Options: date_desc (default), date_asc,
            popular_desc, popular_asc
        duration: Duration filter. Options: within_last_day,
            within_last_week, within_last_month
        offset: Pagination offset (starts at 0, increments by 30)
    """
    result = pixiv().search_illust(
        word=word, search_target=search_target, sort=sort,
        duration=duration, offset=offset,
    )
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    summary = {
        "total": len(illusts),
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@server.tool()
def search_user(word: str, offset: int | None = None) -> str:
    """Search users on Pixiv by keyword.

    Args:
        word: Username or keyword to search
        offset: Pagination offset
    """
    result = pixiv().search_user(word=word, offset=offset)
    user_prefs = result.get("user_previews", [])
    users = []
    for up in user_prefs:
        u = up.get("user", {})
        users.append({
            "id": u.get("id"),
            "name": u.get("name", ""),
            "account": u.get("account", ""),
            "profile_image": (u.get("profile_image_urls") or {}).get("medium", ""),
            "comment": u.get("comment", ""),
            "illusts": [_summarise_illust(i) for i in up.get("illusts", [])[:3]],
        })
    next_offset = (offset or 0) + 30 if len(user_prefs) == 30 else None
    return json.dumps({
        "total": len(users),
        "next_offset": next_offset,
        "users": users,
    }, ensure_ascii=False, indent=2)


@server.tool()
def search_autocomplete(word: str) -> str:
    """Get tag autocomplete suggestions from Pixiv.

    Args:
        word: Partial tag to autocomplete
    """
    result = pixiv().search_autocomplete(word=word)
    tags = result.get("tags", [])
    return json.dumps({
        "tags": [{"name": t.get("name", ""), "access_count": t.get("access_count", 0)}
                 for t in tags[:20]],
    }, ensure_ascii=False, indent=2)


@server.tool()
def trending_tags_illust() -> str:
    """Get trending illustration tags on Pixiv right now."""
    result = pixiv().trending_tags_illust()
    tags = result.get("trending_tags", [])
    return json.dumps({
        "trending_tags": [
            {
                "tag": t.get("tag", ""),
                "translated_name": t.get("translated_name", ""),
                "illust": _summarise_illust(t.get("illust") or {}),
            }
            for t in tags[:20]
        ],
    }, ensure_ascii=False, indent=2)


@server.tool()
def illust_ranking(
    mode: str = "day",
    offset: int | None = None,
    date: str | None = None,
) -> str:
    """Get Pixiv illustration ranking.

    Args:
        mode: Ranking mode.
            day (daily), week (weekly), month (monthly),
            day_male (daily male), day_female (daily female),
            week_original, week_rookie, day_r18, week_r18
        offset: Pagination offset
        date: Specific date in 'YYYY-MM-DD' format
    """
    result = pixiv().illust_ranking(mode=mode, offset=offset, date=date)
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    return json.dumps({
        "mode": mode,
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }, ensure_ascii=False, indent=2)


@server.tool()
def illust_detail(illust_id: int) -> str:
    """Get detailed information about a specific illustration.

    Args:
        illust_id: The ID of the illustration
    """
    result = pixiv().illust_detail(illust_id=illust_id)
    illust = result.get("illust", {})
    if not illust:
        return json.dumps({"error": "Illustration not found"})
    detail = _summarise_illust(illust)
    detail["caption"] = illust.get("caption", "")[:500]
    detail["tags"] = [
        {"name": t.get("name", ""), "translated_name": t.get("translated_name")}
        for t in (illust.get("tags") or [])
    ]
    detail["image_urls"] = illust.get("image_urls", {})
    detail["meta_pages_count"] = len(illust.get("meta_pages", []))
    meta_single = illust.get("meta_single_page", {})
    if meta_single.get("original_image_url"):
        detail["original_image_url"] = meta_single["original_image_url"]
    return json.dumps(detail, ensure_ascii=False, indent=2)


@server.tool()
def illust_related(illust_id: int, offset: int | None = None) -> str:
    """Get illustrations related to a given illustration.

    Args:
        illust_id: Source illustration ID
        offset: Pagination offset
    """
    result = pixiv().illust_related(illust_id=illust_id, offset=offset)
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    return json.dumps({
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }, ensure_ascii=False, indent=2)


@server.tool()
def illust_recommended(offset: int | None = None) -> str:
    """Get recommended illustrations for the logged-in user.

    Args:
        offset: Pagination offset
    """
    result = pixiv().illust_recommended(offset=offset)
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    return json.dumps({
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }, ensure_ascii=False, indent=2)


@server.tool()
def illust_follow(offset: int | None = None, restrict: str = "all") -> str:
    """Get illustrations from users you follow.

    Args:
        offset: Pagination offset
        restrict: 'all' (default), 'public', or 'private'
    """
    result = pixiv().illust_follow(offset=offset, restrict=restrict)
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    return json.dumps({
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }, ensure_ascii=False, indent=2)


@server.tool()
def user_bookmarks(
    user_id: int,
    offset: int | None = None,
    restrict: str = "public",
) -> str:
    """Get a user's bookmarked illustrations.

    Args:
        user_id: Target user ID
        offset: Pagination offset
        restrict: 'public' (default) or 'private'
    """
    result = pixiv().user_bookmarks_illust(
        user_id=user_id, offset=offset, restrict=restrict,
    )
    illusts = _extract_illusts(result)
    next_offset = (offset or 0) + 30 if len(illusts) == 30 else None
    return json.dumps({
        "next_offset": next_offset,
        "illusts": [_summarise_illust(i) for i in illusts],
    }, ensure_ascii=False, indent=2)


@server.tool()
def user_following(
    user_id: int,
    offset: int | None = None,
    restrict: str = "public",
) -> str:
    """Get the list of users a user follows.

    Args:
        user_id: Target user ID
        offset: Pagination offset
        restrict: 'public' (default) or 'private'
    """
    result = pixiv().user_following(
        user_id=user_id, offset=offset, restrict=restrict,
    )
    users = result.get("user_previews", [])
    following = []
    for up in users:
        u = up.get("user", {})
        following.append({
            "id": u.get("id"),
            "name": u.get("name", ""),
            "account": u.get("account", ""),
            "profile_image": (u.get("profile_image_urls") or {}).get("medium", ""),
        })
    next_offset = (offset or 0) + 30 if len(users) == 30 else None
    return json.dumps({
        "next_offset": next_offset,
        "users": following,
    }, ensure_ascii=False, indent=2)


@server.tool()
def download(
    illust_id: int,
    output_dir: str | None = None,
    wait: bool = False,
) -> str:
    """Download a single Pixiv illustration (async by default).

    For multi-page manga and ugoira (animated) works, a sub-folder is
    created automatically. Ugoira is converted to GIF if FFmpeg is
    available.

    Args:
        illust_id: The ID of the illustration to download
        output_dir: Output directory (default: ./pixiv_downloads)
        wait: If true, wait for download to complete before returning
    """
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "pixiv_downloads")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        detail = pixiv().illust_detail(illust_id=illust_id)
    except Exception as e:
        return json.dumps({"error": f"Illustration {illust_id} not found: {e}"})
    illust = detail.get("illust")
    if not illust:
        return json.dumps({"error": f"Illustration {illust_id} not found"})

    mgr = downloader()
    job_id = mgr.submit(illust, output_dir)

    if wait:
        result = mgr.wait_for_job(job_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    return json.dumps({
        "job_id": job_id,
        "status": "submitted",
        "title": illust.get("title"),
        "message": "Download started in background. Use list_downloads to check status.",
    }, ensure_ascii=False, indent=2)


@server.tool()
def download_batch(
    illust_ids: list[int],
    output_dir: str | None = None,
    wait: bool = False,
) -> str:
    """Download multiple Pixiv illustrations (async by default).

    Args:
        illust_ids: List of illustration IDs to download
        output_dir: Output directory (default: ./pixiv_downloads)
        wait: If true, wait for all downloads to complete
    """
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "pixiv_downloads")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    mgr = downloader()
    job_ids = []
    for iid in illust_ids:
        try:
            detail = pixiv().illust_detail(illust_id=iid)
            illust = detail.get("illust")
            if illust:
                jid = mgr.submit(illust, output_dir)
                job_ids.append({"illust_id": iid, "job_id": jid, "title": illust.get("title")})
            else:
                job_ids.append({"illust_id": iid, "error": "Not found"})
        except Exception as e:
            job_ids.append({"illust_id": iid, "error": str(e)})

    if wait:
        results = []
        for j in job_ids:
            if "job_id" in j:
                results.append(mgr.wait_for_job(j["job_id"]))
        return json.dumps(results, ensure_ascii=False, indent=2)

    return json.dumps({
        "submitted": len([j for j in job_ids if "job_id" in j]),
        "failed": len([j for j in job_ids if "error" in j]),
        "jobs": job_ids,
        "message": "Downloads started in background. Use list_downloads to check status.",
    }, ensure_ascii=False, indent=2)


@server.tool()
def download_random_from_recommendation(
    count: int = 1,
    output_dir: str | None = None,
    wait: bool = False,
) -> str:
    """Download random illustrations from the recommended list.

    Args:
        count: Number of random illustrations to download (default: 1)
        output_dir: Output directory (default: ./pixiv_downloads)
        wait: If true, wait for downloads to complete
    """
    import random

    result = pixiv().illust_recommended()
    illusts = _extract_illusts(result)
    if not illusts:
        return json.dumps({"error": "No recommendations available"})

    selected = random.sample(illusts, min(count, len(illusts)))

    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "pixiv_downloads")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    mgr = downloader()
    job_ids = []
    for illust in selected:
        jid = mgr.submit(illust, output_dir)
        job_ids.append({"illust_id": illust["id"], "job_id": jid, "title": illust.get("title")})

    if wait:
        results = [mgr.wait_for_job(j["job_id"]) for j in job_ids]
        return json.dumps(results, ensure_ascii=False, indent=2)

    return json.dumps({
        "jobs": job_ids,
        "message": "Random downloads started in background. Use list_downloads to check status.",
    }, ensure_ascii=False, indent=2)


@server.tool()
def list_downloads() -> str:
    """List status of all download jobs."""
    mgr = downloader()
    jobs = mgr.list_jobs()
    if not jobs:
        return json.dumps({"message": "No download jobs"}, ensure_ascii=False)
    return json.dumps(jobs, ensure_ascii=False, indent=2)


@server.tool()
def download_status(job_id: int) -> str:
    """Check status of a specific download job.

    Args:
        job_id: The job ID (same as illust_id)
    """
    mgr = downloader()
    status = mgr.get_status(job_id)
    if not status:
        return json.dumps({"error": f"Job {job_id} not found"})
    return json.dumps(status, ensure_ascii=False, indent=2)


@server.tool()
def refresh_token() -> str:
    """Manually refresh the Pixiv access token."""
    try:
        result = pixiv().refresh_token()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Token refresh failed: {e}"}, ensure_ascii=False)


@server.tool()
def check_setup() -> str:
    """Check if the Pixiv MCP server is properly configured."""
    info = {}
    phpsessid = get_phpsessid()
    token = get_refresh_token()
    info["phpsessid_configured"] = phpsessid is not None
    info["refresh_token_configured"] = token is not None
    info["ffmpeg_detected"] = detect_ffmpeg() is not None
    info["ffmpeg_path"] = detect_ffmpeg()

    if phpsessid or token:
        try:
            r = pixiv().refresh_token()
            info["auth_status"] = r.get("message") or r.get("access_token", "OK")[:30]
            info["auth_valid"] = True
        except Exception as e:
            info["auth_valid"] = False
            info["suggestion"] = f"Auth failed: {e}. Run `python get_token.py` to re-authenticate."
    else:
        info["auth_valid"] = False
        info["suggestion"] = "No auth configured. Set PIXIV_PHPSESSID or PIXIV_REFRESH_TOKEN in .env"

    return json.dumps(info, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")
