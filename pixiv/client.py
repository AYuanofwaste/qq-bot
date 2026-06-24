"""Pixiv API client wrapper — supports PHPSESSID (cookie) or OAuth token."""

import json
import logging
import os
import sys
import time
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from pixivpy3 import AppPixivAPI, PixivError
from tqdm import tqdm

from auth import get_refresh_token, save_refresh_token, get_access_token, save_access_token, get_phpsessid

logger = logging.getLogger("pixiv-mcp")

MAX_RETRIES = 3
RETRY_DELAY = 2


def retry_on_failure(func):
    """Decorator: retry API calls on failure with token refresh on 401."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(self, *args, **kwargs)
            except PixivError as e:
                status = getattr(e, "status_code", 0) or (
                    401 if "401" in str(e) else 0
                )
                if "404" in str(e):
                    raise PixivError(f"作品不存在 (404)")
                if status in (401, 403) and attempt < MAX_RETRIES and self._use_oauth:
                    logger.info("Token expired, refreshing...")
                    self._login_oauth()
                    continue
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    logger.warning(
                        f"API call failed (attempt {attempt}/{MAX_RETRIES}): {e}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"API call failed after {MAX_RETRIES} attempts: {e}")
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    logger.warning(
                        f"Unexpected error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"Unexpected error after {MAX_RETRIES} attempts: {e}"
                    )
        raise last_error or RuntimeError("Unknown API error")

    return wrapper


class PixivService:
    """Pixiv API client — supports PHPSESSID (cookie) or OAuth token."""

    def __init__(self):
        self._session = None
        self._api = None  # AppPixivAPI instance for OAuth mode
        self._use_oauth = False
        self._login()

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _web_get(self, path: str, params: dict | None = None) -> dict:
        """GET a pixiv web API (ajax) endpoint using the managed session."""
        url = f"https://www.pixiv.net/ajax{path}"
        r = self._session.get(
            url, params=params,
            headers={"Referer": "https://www.pixiv.net/"},
            timeout=30,
        )
        if r.status_code != 200:
            raise PixivError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    @staticmethod
    def _extract_body(data: dict) -> dict:
        body = data.get("body", data)
        if isinstance(body, dict) and body.get("error"):
            raise PixivError(f"API error: {body.get('message', body)}")
        return body or {}

    @staticmethod
    def _extract_list(data: dict, key: str) -> list:
        body = PixivService._extract_body(data)
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for k in (key, "list", "items", "works"):
                if k in body and isinstance(body[k], list):
                    return body[k]
            if key in body:
                v = body[key]
                return v if isinstance(v, list) else [v]
        return []

    @staticmethod
    def _convert_detail(body: dict) -> dict:
        """Convert web API illust detail to pixivpy3 nested format."""
        raw_tags = body.get("tags", {})
        tags_list = raw_tags.get("tags", []) if isinstance(raw_tags, dict) else []
        return {
            "id": body.get("id"),
            "title": body.get("title", ""),
            "type": ["illust", "manga", "ugoira"][body.get("illustType", 0)] if body.get("illustType") is not None else "illust",
            "page_count": body.get("pageCount", 1),
            "user": {
                "id": body.get("userId"),
                "name": body.get("userName", ""),
                "account": body.get("userAccount", ""),
            },
            "tags": [
                {"name": t.get("tag", ""), "translated_name": (t.get("translation") or {}).get("en")}
                for t in tags_list
            ],
            "width": body.get("width"),
            "height": body.get("height"),
            "total_bookmarks": body.get("bookmarkCount", 0),
            "total_view": body.get("viewCount", 0),
            "create_date": body.get("createDate", ""),
            "image_urls": {
                "medium": body.get("urls", {}).get("small", ""),
                "large": body.get("urls", {}).get("regular", ""),
                "square_medium": body.get("urls", {}).get("thumb", ""),
            },
            "meta_pages": [],
            "meta_single_page": {"original_image_url": body.get("urls", {}).get("original", "")},
            "caption": body.get("description", ""),
            "total_comments": body.get("commentCount", 0),
            "is_bookmarked": body.get("isBookmarked", False),
            "bookmark_data": body.get("bookmarkData"),
            "sanity_level": body.get("sl", 0),
            "illust_ai_type": body.get("aiType", 0),
        }

    @staticmethod
    def _flat_to_nested(item: dict) -> dict:
        """Convert flat web API illust format to pixivpy3 nested format."""
        tags = item.get("tags", [])
        if tags and isinstance(tags[0], str):
            tags = [{"name": t, "translated_name": None} for t in tags]
        url = item.get("url", "")
        return {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "type": ["illust", "manga", "ugoira"][item.get("illustType", 0)] if item.get("illustType") is not None else "illust",
            "page_count": item.get("pageCount", 1),
            "user": {
                "id": item.get("userId"),
                "name": item.get("userName", ""),
                "account": item.get("userAccount", ""),
            },
            "tags": tags,
            "width": item.get("width"),
            "height": item.get("height"),
            "total_bookmarks": 0,
            "total_view": 0,
            "create_date": item.get("createDate", ""),
            "image_urls": {
                "medium": url,
                "large": url.replace("c/250x250_80_a2", "c/540x540_70"),
                "square_medium": url,
            },
            "meta_pages": [],
            "meta_single_page": {},
            "is_bookmarked": item.get("bookmarkData") is not None,
            "visibility": item.get("xRestrict", 0),
            "sanity_level": item.get("sl", 0),
            "illust_ai_type": item.get("aiType", 0),
        }

    # ── Login ────────────────────────────────────────────────────────

    def _login(self):
        import cloudscraper

        phpsessid = get_phpsessid()
        if phpsessid:
            sess = cloudscraper.create_scraper(
                browser={"browser": "firefox", "platform": "windows", "mobile": False},
            )
            sess.cookies.set("PHPSESSID", phpsessid, domain=".pixiv.net")
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.pixiv.net/",
            })
            try:
                r = sess.get("https://www.pixiv.net/", timeout=15)
                if r.status_code == 200 and '"userId"' in r.text:
                    logger.info("PHPSESSID 登录成功")
                    self._session = sess
                    self._use_oauth = False
                    return
                logger.warning("PHPSESSID 无效 (status=%s, len=%s), 尝试 OAuth...", r.status_code, len(r.text))
            except Exception as e:
                logger.warning("PHPSESSID 请求失败: %s, 尝试 OAuth...", e)

        self._login_oauth()

    def _login_oauth(self):
        import cloudscraper

        token = get_refresh_token()
        if not token:
            raise RuntimeError(
                "没有有效的认证方式。请在 .env 中设置 PIXIV_PHPSESSID 或 PIXIV_REFRESH_TOKEN"
            )
        self._api = AppPixivAPI()
        try:
            result = self._api.auth(refresh_token=token)
            save_access_token(self._api.access_token)
            new_refresh = getattr(result.response, "refresh_token", None)
            if new_refresh and new_refresh != token:
                save_refresh_token(new_refresh)
        except PixivError as e:
            if "401" in str(e) or "403" in str(e):
                raise RuntimeError(
                    "Pixiv refresh token 已失效。运行 `python get_token.py` 重新获取。"
                ) from e
            raise
        sess = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "windows", "mobile": False},
        )
        sess.headers.update({
            "Authorization": f"Bearer {self._api.access_token}",
            "User-Agent": "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)",
            "Referer": "https://app-api.pixiv.net/",
        })
        self._session = sess
        self._use_oauth = True

    # ── Search ──────────────────────────────────────────────────────

    @retry_on_failure
    def search_illust(self, word: str, search_target: str = "partial_match_for_tags",
                      sort: str = "date_desc", duration: str | None = None,
                      offset: int | None = None) -> dict:
        if self._use_oauth:
            return self._api.search_illust(
                word=word, search_target=search_target, sort=sort,
                duration=duration, offset=offset, req_auth=True,
            )
        import urllib.parse
        encoded_word = urllib.parse.quote(word)
        params = {"order": "date_d" if sort == "date_desc" else "date", "offset": offset}
        data = self._web_get(f"/search/illustrations/{encoded_word}", params)
        body = self._extract_body(data)
        raw = (body.get("illust") or {}).get("data", [])
        return {"illusts": [self._flat_to_nested(i) for i in raw]}

    @retry_on_failure
    def search_user(self, word: str, offset: int | None = None) -> dict:
        if self._use_oauth:
            return self._api.search_user(word=word, offset=offset, req_auth=True)
        raise PixivError("用户搜索功能需要 OAuth 认证，PHPSESSID 模式下暂不支持")

    @retry_on_failure
    def search_autocomplete(self, word: str) -> dict:
        if self._use_oauth:
            url = f"{self._api.hosts}/v1/search/autocomplete"
            params = {"word": word}
            r = self._api.requests_call("GET", url, params=params)
            return self._api.parse_result(r)
        import urllib.parse
        encoded_word = urllib.parse.quote(word)
        data = self._web_get(f"/search/autocomplete/{encoded_word}")
        tags = self._extract_list(data, "tags")
        return {"tags": [{"name": t.get("name", word), "access_count": 0} for t in tags] if tags else []}

    @retry_on_failure
    def trending_tags_illust(self) -> dict:
        if self._use_oauth:
            return self._api.trending_tags_illust(req_auth=True)
        raise PixivError("趋势标签功能需要 OAuth 认证，PHPSESSID 模式下暂不支持")

    # ── Ranking ─────────────────────────────────────────────────────

    @retry_on_failure
    def illust_ranking(self, mode: str = "day", offset: int | None = None,
                       date: str | None = None) -> dict:
        if self._use_oauth:
            return self._api.illust_ranking(
                mode=mode, offset=offset, date=date, req_auth=True,
            )
        raise PixivError("排行榜功能需要 OAuth 认证，PHPSESSID 模式下暂不支持")

    # ── Illust details & related ────────────────────────────────────

    @retry_on_failure
    def illust_detail(self, illust_id: int) -> dict:
        if self._use_oauth:
            return self._api.illust_detail(illust_id=illust_id, req_auth=True)
        data = self._web_get(f"/illust/{illust_id}")
        body = self._extract_body(data)
        if not body or body.get("id") is None:
            return {"illust": {}}
        return {"illust": self._convert_detail(body)}

    @retry_on_failure
    def illust_related(self, illust_id: int, offset: int | None = None) -> dict:
        if self._use_oauth:
            url = f"{self._api.hosts}/v2/illust/related"
            params = {"illust_id": illust_id}
            if offset is not None:
                params["offset"] = offset
            r = self._api.requests_call("GET", url, params=params, req_auth=True)
            return self._api.parse_result(r)
        limit = 20
        data = self._web_get(f"/illust/{illust_id}/recommend/init", {"limit": limit})
        body = self._extract_body(data)
        raw = body.get("illusts", [])
        raw = [i for i in raw if isinstance(i, dict)]
        return {"illusts": [self._flat_to_nested(i) for i in raw]}

    @retry_on_failure
    def illust_recommended(self, offset: int | None = None) -> dict:
        if self._use_oauth:
            return self._api.illust_recommended(offset=offset, req_auth=True)
        data = self._web_get("/top/illust", {"mode": "all"})
        body = self._extract_body(data)
        page = body.get("page", {})
        raw = []
        for key in ("recommend", "ranking", "popular", "new"):
            val = page.get(key, [])
            if isinstance(val, list):
                raw = val
                break
        # 过滤掉非字典元素（比如纯 ID 字符串）
        raw = [i for i in raw if isinstance(i, dict)]
        return {"illusts": [self._flat_to_nested(i) for i in raw]}

    @retry_on_failure
    def illust_follow(self, offset: int | None = None, restrict: str = "all") -> dict:
        if self._use_oauth:
            url = f"{self._api.hosts}/v2/illust/follow"
            params = {"restrict": restrict}
            if offset is not None:
                params["offset"] = offset
            r = self._api.requests_call("GET", url, params=params, req_auth=True)
            return self._api.parse_result(r)
        raise PixivError("illust_follow 需要 OAuth 认证，PHPSESSID 模式下不支持")

    @retry_on_failure
    def ugoira_metadata(self, illust_id: int) -> dict:
        if self._use_oauth:
            return self._api.ugoira_metadata(illust_id=illust_id, req_auth=True)
        data = self._web_get(f"/illust/{illust_id}/ugoira")
        body = self._extract_body(data)
        if body.get("frames"):
            return {
                "ugoira_metadata": {
                    "zip_urls": {"medium": body.get("originalSrc", "")},
                    "frames": [{"file": f.get("file", ""), "delay": f.get("delay", 50)} for f in body["frames"]],
                }
            }
        return {"ugoira_metadata": {"zip_urls": {}, "frames": []}}

    # ── User ─────────────────────────────────────────────────────────

    @retry_on_failure
    def user_detail(self, user_id: int) -> dict:
        if self._use_oauth:
            return self._api.user_detail(user_id=user_id, req_auth=True)
        data = self._web_get(f"/user/{user_id}")
        body = self._extract_body(data)
        return {"user": {
            "id": body.get("userId"),
            "name": body.get("name", ""),
            "account": body.get("account", ""),
            "comment": body.get("comment", ""),
            "profile_image_urls": {"medium": body.get("image", "")},
        }}

    @retry_on_failure
    def user_illusts(self, user_id: int, offset: int | None = None) -> dict:
        if self._use_oauth:
            return self._api.user_illusts(user_id=user_id, offset=offset, req_auth=True)
        data = self._web_get(f"/user/{user_id}/profile/all")
        ids = list(self._extract_body(data).get("illusts", {}).keys())
        if offset:
            ids = ids[offset:]
        return {"illusts": [{"id": iid, "title": "", "user": {"id": user_id}} for iid in ids[:30]]}

    @retry_on_failure
    def user_bookmarks_illust(self, user_id: int, offset: int | None = None,
                               restrict: str = "public") -> dict:
        if self._use_oauth:
            return self._api.user_bookmarks_illust(
                user_id=user_id, offset=offset, restrict=restrict, req_auth=True,
            )
        raise PixivError("用户收藏功能需要 OAuth 认证，PHPSESSID 模式下暂不支持")

    @retry_on_failure
    def user_following(self, user_id: int, offset: int | None = None,
                       restrict: str = "public") -> dict:
        if self._use_oauth:
            url = f"{self._api.hosts}/v1/user/following"
            params = {"user_id": user_id, "restrict": restrict}
            if offset is not None:
                params["offset"] = offset
            r = self._api.requests_call("GET", url, params=params, req_auth=True)
            return self._api.parse_result(r)
        raise PixivError("user_following 需要 OAuth 认证，PHPSESSID 模式下不支持")

    # ── Utility ──────────────────────────────────────────────────────

    def _gen_page_urls(self, base_url: str, page_count: int) -> list[str]:
        if page_count <= 1 or "_p0" not in base_url:
            return [base_url]
        return [base_url.replace("_p0", f"_p{i}", 1) for i in range(page_count)]

    def get_illust_image_urls(self, illust: dict) -> list[str]:
        page_count = illust.get("page_count", 1)
        if illust.get("type") == "ugoira":
            meta = illust.get("ugoira_metadata", {})
            frame_urls = [f.get("file") for f in meta.get("frames", [])]
            if frame_urls and frame_urls[0]:
                return frame_urls
        pages = illust.get("meta_pages", [])
        if pages:
            return [p["image_urls"]["large"] for p in pages]
        # Try original URL first for best quality
        single = illust.get("meta_single_page", {})
        orig = single.get("original_image_url", "")
        if orig:
            return self._gen_page_urls(orig, page_count)
        base = illust.get("image_urls", {}).get("large", "")
        if base:
            return self._gen_page_urls(base, page_count)
        return []

    @retry_on_failure
    def download_image(self, url: str, path: str, **kwargs) -> bool:
        r = self._session.get(url, stream=True, timeout=60)
        if r.status_code != 200:
            raise PixivError(f"Download failed: HTTP {r.status_code}")
        total = int(r.headers.get("content-length", 0))
        with open(path, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, unit_divisor=1024,
                      desc=f"  {Path(path).name}", file=sys.stderr,
                      disable=total == 0) as pbar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
        return True

    @retry_on_failure
    def download(self, illust_id: int, output_dir: str | None = None,
                 wait: bool = False) -> str:
        return json.dumps(self._inner_download(illust_id, output_dir, wait))

    def _inner_download(self, illust_id: int, output_dir: str | None = None,
                        wait: bool = False) -> dict:
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), "pixiv_downloads")
        detail = self.illust_detail(illust_id)
        illust = detail.get("illust", {})
        if not illust:
            return {"error": f"作品 {illust_id} 找不到"}
        os.makedirs(output_dir, exist_ok=True)
        from downloader import get_manager
        mgr = get_manager()
        job_id = mgr.submit(illust, output_dir)
        if wait:
            return mgr.wait_for_job(job_id)
        return {"job_id": job_id, "status": "submitted", "title": illust.get("title")}

    def refresh_token(self):
        if self._use_oauth:
            self._login_oauth()
            return {"access_token": self._api.access_token[:20] + "..."}
        return {"message": "使用 PHPSESSID 认证，无需 token"}
