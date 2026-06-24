import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
import yt_dlp
from tqdm import tqdm

logger = logging.getLogger("bilibili_dl")


class _YdlLogger:
    def debug(self, msg): pass
    def info(self, msg): logger.info(msg)
    def warning(self, msg): logger.warning(msg)
    def error(self, msg): logger.error(msg)

BILI_OUTPUT = Path(__file__).resolve().parent / "downloads"

BVID_PATTERN = re.compile(
    r"(?:https?://)?"
    r"(?:www\.|m\.)?"
    r"(?:bilibili\.com/(?:video/)?|b23\.tv/)?"
    r"(BV[0-9A-Za-z]{10})"
)


def extract_bvid(text: str) -> str | None:
    m = BVID_PATTERN.search(text)
    if m:
        return m.group(1)
    if "b23.tv" in text:
        return _resolve_b23(text)
    return None


def _resolve_b23(url: str) -> str | None:
    if not url.startswith("http"):
        url = "https://" + url
    try:
        resp = requests.get(url, allow_redirects=True, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        m = BVID_PATTERN.search(resp.url)
        return m.group(1) if m else None
    except Exception as e:
        logger.warning("Failed to resolve b23.tv URL: %s", e)
        return None


COOKIES_FILE = Path(__file__).resolve().parent / "bilibili_cookies.txt"
BACKUP_COOKIES = Path(__file__).resolve().parent.parent / "bilibili_cookies.txt"


def _get_ydl_opts(output_dir: str) -> dict:
    progress_bar = None

    def _progress_hook(d):
        nonlocal progress_bar
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if progress_bar is None and total:
                progress_bar = tqdm(
                    total=total, unit="B", unit_scale=True, unit_divisor=1024,
                    desc="  B站视频", file=sys.stderr,
                )
            if progress_bar and d.get("downloaded_bytes"):
                progress_bar.n = d["downloaded_bytes"]
                progress_bar.refresh()
        elif d["status"] == "finished":
            if progress_bar:
                progress_bar.close()
                progress_bar = None

    opts = {
        "format": "bv[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": str(Path(output_dir) / "%(id)s_%(title).80B.%(ext)s"),
        "merge_output_format": "mp4",
        "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
        "progress_hooks": [_progress_hook],
        "retries": 20,
        "fragment_retries": 20,
        "continuedl": True,
        "skip_unavailable_fragments": False,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        },
        "logger": _YdlLogger(),
    }

    for candidate in (COOKIES_FILE, BACKUP_COOKIES):
        if candidate.exists():
            opts["cookiefile"] = str(candidate)
            break

    cookies_file = os.environ.get("BILIBILI_COOKIES_FILE", "")
    if cookies_file and Path(cookies_file).exists():
        opts["cookiefile"] = cookies_file

    return opts


MAX_QQ_VIDEO_SIZE = 80 * 1024 * 1024  # 80MB, QQ inline video limit ~100MB


def _compress_for_qq(src: Path) -> Path:
    compressed = src.with_stem(src.stem + "_qq")
    if compressed.exists():
        return compressed
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-preset", "fast",
        "-vf", "scale='min(720,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
        "-b:v", "1M", "-maxrate", "1.5M", "-bufsize", "2M",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(compressed),
    ], check=True, capture_output=True, timeout=600)
    logger.info("Compressed %s -> %s (%d MB)", src.name, compressed.name,
                compressed.stat().st_size // 1024 // 1024)
    return compressed


def download_video(url: str, output_dir: str | None = None) -> str:
    if not url.startswith("http"):
        url = f"https://www.bilibili.com/video/{url}"

    out_dir = Path(output_dir) if output_dir else BILI_OUTPUT
    out_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = _get_ydl_opts(str(out_dir))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "未知标题")
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
        bvid = info.get("id", "unknown")
        ext = info.get("ext", "mp4")

        output_path = out_dir / f"{bvid}_{safe_title}.{ext}"
        part_files = list(out_dir.glob(f"{bvid}_*.part"))
        for pf in part_files:
            pf.unlink(missing_ok=True)
        if output_path.exists():
            logger.info("Video already downloaded: %s", output_path)
            return str(output_path)

        try:
            ydl.download([url])
        except Exception:
            for pf in out_dir.glob(f"{bvid}_*.part"):
                pf.unlink(missing_ok=True)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise

    candidates = list(out_dir.glob(f"{bvid}_*"))
    result = str(candidates[0]) if candidates else str(output_path)

    result_path = Path(result)
    if result_path.stat().st_size > MAX_QQ_VIDEO_SIZE:
        result = str(_compress_for_qq(result_path))

    return result
