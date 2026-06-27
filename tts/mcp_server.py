"""TTS MCP Server — wraps Bert-VITS2 HTTP server as MCP service."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from defaults import TTS_DEFAULTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tts-mcp")

TTS_DIR = Path(__file__).parent
HTTP_URL = "http://127.0.0.1:9880"
_http_proc: asyncio.subprocess.Process | None = None
_ready = False


@asynccontextmanager
async def server_lifespan(app):
    global _http_proc, _ready
    logger.info("启动 TTS HTTP server...")
    _http_proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(TTS_DIR / "server.py"),
        "-y",
        str(TTS_DIR / "config.yml"),
        cwd=str(TTS_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(), timeout=2) as c:
        for i in range(120):
            try:
                r = await c.get(f"{HTTP_URL}/docs")
                if r.status_code == 200:
                    _ready = True
                    logger.info("TTS HTTP server 就绪")
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        else:
            logger.warning("TTS HTTP server 启动超时")
    try:
        yield
    finally:
        if _http_proc:
            _http_proc.kill()
            logger.info("TTS HTTP server 已关闭")


server = FastMCP("tts-server", lifespan=server_lifespan)


@server.tool()
def synthesize(
    text: str,
    model_id: int = 0,
    speaker_name: str = "Azuma",
    sdp_ratio: float = TTS_DEFAULTS["sdp_ratio"],
    noise: float = TTS_DEFAULTS["noise"],
    noisew: float = TTS_DEFAULTS["noisew"],
    length: float = TTS_DEFAULTS["length"],
    language: str = "ZH",
    auto_split: bool = True,
) -> str:
    """Generate TTS audio and return path to WAV file."""
    if not _ready:
        return "ERROR: TTS server not ready"

    params = {
        "text": text,
        "model_id": model_id,
        "speaker_name": speaker_name,
        "sdp_ratio": sdp_ratio,
        "noise": noise,
        "noisew": noisew,
        "length": length,
        "language": language,
        "auto_split": auto_split,
    }

    try:
        with httpx.Client(transport=httpx.HTTPTransport(), timeout=120) as client:
            resp = client.get(f"{HTTP_URL}/voice", params=params)
    except Exception as e:
        return f"ERROR: {e}"

    if resp.status_code != 200:
        return f"ERROR: {resp.text[:200]}"

    ts = int(asyncio.get_event_loop().time())
    wav_dir = TTS_DIR / "tts_output"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_path = wav_dir / f"voice_{ts}.wav"
    wav_path.write_bytes(resp.content)
    return str(wav_path)


if __name__ == "__main__":
    server.run(transport="stdio")
