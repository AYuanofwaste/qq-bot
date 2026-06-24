"""Async download manager for Pixiv illustrations."""

import os
import re
import sys
import json
import time
import logging
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from client import PixivService

logger = logging.getLogger("pixiv-mcp.downloader")

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TRAILING_DOT = re.compile(r'[. ]+$')


def clean_filename(name: str, max_len: int = 200) -> str:
    """Remove characters that are invalid on Windows filesystems."""
    name = INVALID_CHARS.sub("_", name)
    name = TRAILING_DOT.sub("", name)
    name = name.strip()
    if not name:
        name = "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip("._ ")
    return name


def detect_ffmpeg() -> str | None:
    """Return path to ffmpeg if available, else None."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Common Windows paths
    for candidate in [
        "C:/ffmpeg/bin/ffmpeg.exe",
        "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
        os.path.expanduser("~/ffmpeg/bin/ffmpeg.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


def _frames_to_gif(ffmpeg_path: str, frames_dir: str, output_path: str,
                   frame_delays: list[int]):
    """Convert a sequence of frame images to GIF using ffmpeg."""
    palette_path = os.path.join(tempfile.gettempdir(), "palette.png")
    try:
        subprocess.run(
            [ffmpeg_path, "-y", "-framerate", "10",
             "-pattern_type", "glob", "-i", f"{frames_dir}/*",
             "-vf", "fps=10,palettegen=max_colors=256:stats_mode=diff",
             palette_path],
            capture_output=True, timeout=120,
        )
        delay_str = ",".join(str(d) for d in frame_delays)
        subprocess.run(
            [ffmpeg_path, "-y", "-framerate", "10",
             "-pattern_type", "glob", "-i", f"{frames_dir}/*",
             "-i", palette_path, "-lavfi",
             f"fps=10,paletteuse=dither=bayer:bayer_scale=3",
             output_path],
            capture_output=True, timeout=120,
        )
    finally:
        if os.path.isfile(palette_path):
            os.remove(palette_path)


class DownloadJob:
    """Represents a single download job."""

    def __init__(self, illust: dict, output_dir: str, service: PixivService,
                 ffmpeg_path: str | None):
        self.illust = illust
        self.illust_id = int(illust["id"]) if not isinstance(illust["id"], int) else illust["id"]
        self.title = illust.get("title", "untitled")
        self.type = illust.get("type", "illust")
        self.output_dir = Path(output_dir)
        self.service = service
        self.ffmpeg_path = ffmpeg_path
        self.status = "pending"
        self.error = None
        self.result_path = None

    def _base_dir(self) -> Path:
        safe_title = clean_filename(self.title)
        if self.type == "ugoira" or self.illust.get("page_count", 1) > 1:
            sub = self.output_dir / f"{self.illust_id}_{safe_title}"
        else:
            sub = self.output_dir
        sub.mkdir(parents=True, exist_ok=True)
        return sub

    def run(self):
        """Execute the download."""
        self.status = "running"
        try:
            if self.type == "ugoira":
                self._download_ugoira()
            elif self.illust.get("page_count", 1) > 1:
                self._download_manga()
            else:
                self._download_single()
            self.status = "completed"
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            logger.error(f"Download failed for illust {self.illust_id}: {e}")

    def _download_single(self):
        urls = self.service.get_illust_image_urls(self.illust)
        if not urls:
            raise RuntimeError("No image URLs found")
        base_dir = self._base_dir()
        url = urls[0]
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".jpg"
        safe_title = clean_filename(self.title)
        fname = f"{self.illust_id}_{safe_title}{ext}"
        fpath = base_dir / fname
        self.service.download_image(url, str(fpath))
        self.result_path = str(fpath)

    def _download_manga(self):
        base_dir = self._base_dir()
        urls = self.service.get_illust_image_urls(self.illust)
        safe_title = clean_filename(self.title)
        downloaded = []
        for i, url in enumerate(urls, 1):
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".jpg"
            fname = f"{self.illust_id:>08d}_{safe_title}_{i:03d}{ext}"
            fpath = base_dir / fname
            self.service.download_image(url, str(fpath))
            downloaded.append(str(fpath))
        self.result_path = str(base_dir)

    def _download_ugoira(self):
        if not self.ffmpeg_path:
            logger.warning(
                f"FFmpeg not found, downloading ugoira {self.illust_id} as frame zip."
            )
            self._download_manga()
            return

        meta = self.service.ugoira_metadata(self.illust_id)
        frames_data = meta.get("ugoira_metadata", {}).get("frames", [])
        if not frames_data:
            raise RuntimeError("No ugoira frame data found")

        base_dir = self._base_dir()
        safe_title = clean_filename(self.title)
        gif_path = base_dir / f"{self.illust_id}_{safe_title}.gif"

        # Download frames
        frame_dir = base_dir / f".frames_{self.illust_id}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for i, frame in enumerate(frames_data, 1):
            url = frame["file"]
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".jpg"
            fname = f"frame_{i:05d}{ext}"
            fpath = frame_dir / fname
            self.service.download_image(url, str(fpath))
            downloaded.append(str(fpath))

        # Convert to GIF
        delays = [f.get("delay", 50) for f in frames_data]
        logger.info(f"Converting ugoira {self.illust_id} to GIF...")
        _frames_to_gif(self.ffmpeg_path, str(frame_dir), str(gif_path), delays)

        # Clean up frame directory
        shutil.rmtree(frame_dir, ignore_errors=True)
        self.result_path = str(gif_path)


class DownloadManager:
    """Manages async background downloads."""

    def __init__(self, max_workers: int = 2):
        self.service = PixivService()
        self.ffmpeg_path = detect_ffmpeg()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.jobs: dict[int, DownloadJob] = {}
        self._futures: dict = {}

        if self.ffmpeg_path:
            logger.info(f"FFmpeg detected: {self.ffmpeg_path}")
        else:
            logger.info("FFmpeg not found. Ugoira (GIF) conversion disabled.")

    def submit(self, illust: dict, output_dir: str) -> int:
        """Submit a download job. Returns the illust_id as job ID."""
        job = DownloadJob(illust, output_dir, self.service, self.ffmpeg_path)
        self.jobs[illust["id"]] = job
        future = self.executor.submit(job.run)
        self._futures[illust["id"]] = future
        return illust["id"]

    def submit_batch(self, illusts: list[dict], output_dir: str) -> list[int]:
        """Submit multiple download jobs."""
        ids = []
        for illust in illusts:
            ids.append(self.submit(illust, output_dir))
        return ids

    def get_status(self, job_id: int) -> dict | None:
        """Get the status of a download job."""
        job = self.jobs.get(job_id)
        if not job:
            return None
        return {
            "illust_id": job.illust_id,
            "title": job.title,
            "type": job.type,
            "status": job.status,
            "error": job.error,
            "result_path": job.result_path,
        }

    def list_jobs(self) -> list[dict]:
        """List all jobs."""
        return [
            self.get_status(jid) for jid in self.jobs
            if self.get_status(jid) is not None
        ]

    def wait_for_job(self, job_id: int, timeout: float | None = None) -> dict:
        """Wait for a specific job to complete."""
        future = self._futures.get(job_id)
        if future:
            future.result(timeout=timeout)
        return self.get_status(job_id) or {}

    def shutdown(self):
        self.executor.shutdown(wait=False)


# Module-level singleton
_manager: DownloadManager | None = None


def get_manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager


def download_illust(illust: dict, output_dir: str) -> int:
    """Convenience: submit a download and return job ID."""
    return get_manager().submit(illust, output_dir)


def download_illusts(illusts: list[dict], output_dir: str) -> list[int]:
    """Convenience: submit batch download."""
    return get_manager().submit_batch(illusts, output_dir)



