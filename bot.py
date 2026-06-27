"""QQ Bot — connects NapCatQQ (OneBot v11) with JMComic, Pixiv, Bilibili services via MCP."""

import asyncio
import httpx
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from aiocqhttp import CQHttp, Event
from aiocqhttp.message import Message

from core.ai_handler import AIHandler
from mcp_client.client import McpManager
from news.global_ import SOURCE_COMMANDS
from news.domestic import fetch_news
from tts import tts_mgr
from tts.commands import handle_tts_switch, tts_speak_text


load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("qq-bot")

TTS_API = os.environ.get("TTS_API", "http://127.0.0.1:9880")

_mcp_manager: McpManager | None = None


def _get_mcp() -> McpManager:
    global _mcp_manager
    if _mcp_manager is None:
        raise RuntimeError("MCP manager not initialized")
    return _mcp_manager


_ai_handler: AIHandler | None = None


def _get_ai() -> AIHandler:
    global _ai_handler
    if _ai_handler is None:
        _ai_handler = AIHandler(_get_mcp())
    return _ai_handler


_token = os.environ.get("BOT_TOKEN", "")
bot = CQHttp(access_token=_token) if _token else CQHttp()


# ── Helpers ──────────────────────────────────────────────────────

async def _resolve_cq_urls(text: str) -> str:
    def _ext(url: str) -> str:
        return Path(url.split("?")[0].split("#")[0]).suffix or ".jpg"

    def _replace(m: re.Match) -> str:
        url = m.group(1)
        ext = _ext(url)
        fname = f"cq_{uuid.uuid4().hex[:12]}{ext}"
        local = Path(tempfile.gettempdir()) / fname
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            local.write_bytes(resp.content)
            return f'[CQ:image,file=file:///{local.as_posix()}]'
        except Exception:
            logger.warning("CQ 图片下载失败，已移除: %s", url)
            return ""

    return re.sub(r'\[CQ:image,file=(https?://[^\]]+)\]', _replace, text)


async def _send_reply(event: Event, message: str):
    processed = await _resolve_cq_urls(message)
    await bot.send(event, Message(processed))


MAX_QQ_FILE_SIZE = 50 * 1024 * 1024


async def _send_file(event: Event, file_path: str):
    path = Path(file_path).resolve()
    if not path.exists():
        logger.warning("文件不存在，无法发送: %s", path)
        return
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > 50:
        logger.warning("文件过大 (%.1fMB)，跳过发送: %s", size_mb, path.name)
        return

    safe_name = _sanitize_filename(path.name)
    if safe_name != path.name:
        new_path = path.with_name(safe_name)
        path.rename(new_path)
        path = new_path

    file_abs = path.as_posix()
    file_name = path.name
    try:
        cq = f"[CQ:file,file=file:///{file_abs},name={file_name}]"
        await bot.send(event, Message(cq))
        logger.info("文件已发送: %s (%.1fMB)", file_name, size_mb)
    except Exception as e:
        logger.warning("CQ:file 发送失败，尝试 upload: %s", e)
        if event.message_type == "private":
            await bot.call_action("upload_private_file", user_id=event.user_id, file=str(path), name=file_name)
        else:
            await bot.call_action("upload_group_file", group_id=event.group_id, file=str(path), name=file_name)
        logger.info("文件已发送 (upload): %s", file_name)


def _sanitize_filename(name: str) -> str:
    """清理文件名，移除CQ码冲突字符和特殊符号，限制长度"""
    name = name.replace("[", "(").replace("]", ")")
    name = re.sub(r"[❤~✨⭐★]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 90:
        p = Path(name)
        base, ext = p.stem, p.suffix
        if len(ext) <= 6:
            name = base[: 90 - len(ext)] + ext
        else:
            name = name[:90]
    return name or "file.pdf"


async def _send_video(event: Event, file_path: str):
    path = Path(file_path).resolve()
    if not path.exists():
        logger.warning("视频不存在: %s", path)
        return
    try:
        file_abs = path.as_posix()
        cq = f"[CQ:video,file=file:///{file_abs}]"
        await bot.send(event, Message(cq))
        logger.info("视频已发送: %s", path)
    except Exception as e:
        logger.warning("CQ:video 发送失败，改用文件发送: %s", e)
        await _send_file(event, file_path)


# ── Message Handler ──────────────────────────────────────────────

@bot.on_message()
async def handle_message(event: Event) -> None:
    raw = event.raw_message.strip()
    logger.info("收到消息: type=%s user=%s text=%r", event.message_type, event.user_id, raw)
    if not raw:
        return

    try:
        await _dispatch_message(event, raw)
    except Exception as e:
        logger.error("handle_message 顶层异常", exc_info=True)
        try:
            await _send_reply(event, f"❌ 处理消息时出错: {e}\n输入 /help 查看可用命令。")
        except Exception:
            pass


async def _dispatch_message(event: Event, raw: str) -> None:
    text = raw
    is_group = event.message_type == "group"
    user_id = event.user_id

    if is_group:
        at_match = re.match(r'^\[CQ:at,qq=(\d+)\]\s*(.*)', raw)
        if at_match:
            at_qq = at_match.group(1)
            if at_qq not in (os.environ.get("BOT_QQ", ""),):
                return
            text = at_match.group(2).strip()
            if not text:
                return
        elif not raw.startswith("/"):
            return

    if text in ("/help", "help", "/start") or text.startswith("帮助"):
        _roles = " / ".join(tts_mgr.list_personae()) if tts_mgr.list_personae() else "Azuma / Taffy"
        await _send_reply(event, (
            "🤖 QQ Bot 命令:\n"
            "  /speak-zhouli <文本>  改写为大周礼腔调\n"
            "  /news             游戏新闻菜单（国内 / 国外）\n"
            "    /国内新闻        ali213 最新 5 条\n"
            "    /国外新闻        显示国外源子菜单（VGC/ResetEra/Insider/Steam）\n"
            "  /help             显示此帮助\n"
            "  /forget           清空 AI 对话记忆\n"
            "\n💬 群聊中 @我 可以和我对话，AI 会自动处理你的请求。\n"
            "例如：「帮我搜一下碧蓝档案的图」「今天P站排行榜」"
        ))
        return

    if text == "/news":
        await _send_reply(event, (
            "📰 游戏新闻菜单\n"
            "  /国内新闻  — ali213 最新 5 条（带图）\n"
            "  /国外新闻  — 显示国外源子菜单"
        ))
        return

    if text == "/国内新闻":
        await _send_reply(event, "📡 正在抓取国内新闻...")
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, fetch_news)
            await _send_reply(event, result)
        except Exception as e:
            logger.error("国内新闻抓取失败: %s", e)
            await _send_reply(event, f"❌ 国内新闻抓取失败: {e}")
        return

    if text == "/国外新闻":
        await _send_reply(event, (
            "🌍 国外游戏热料源（各取最新 5 条，带图+中文翻译）\n"
            "  /vgc      — VGC 新闻\n"
            "  /resetera — ResetEra 爆料帖\n"
            "  /insider  — Insider Gaming（含 Bluesky 镜像）\n"
            "  /steam    — Steam 即将发售\n"
            "💡 翻译需 5-15 秒，请稍候"
        ))
        return

    src_match = re.match(r"^/(vgc|resetera|insider|steam)$", text)
    if src_match:
        name = src_match.group(1)
        fn = SOURCE_COMMANDS.get(name)
        if fn:
            await _send_reply(event, f"🌍 正在抓取 {name}，需翻译请稍候...")
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, fn)
                await _send_reply(event, result)
            except Exception as e:
                logger.error("%s 抓取失败: %s", name, e)
                await _send_reply(event, f"❌ {name} 抓取失败: {e}")
            return

    if text == "/forget":
        try:
            ai = _get_ai()
            cid = f"group:{event.group_id}" if is_group else f"private:{event.user_id}"
            ai.clear_history(cid)
            await _send_reply(event, "🧹 已清空对话记忆，我们重新开始吧～")
        except Exception:
            await _send_reply(event, "🧹 已清空对话记忆")
        return

    zhouli_match = re.match(r"^/speak-zhouli[\s（(]*(.+)$", text, re.DOTALL)
    if zhouli_match:
        text_to_rewrite = zhouli_match.group(1).strip()
        if not text_to_rewrite:
            await _send_reply(event, "用法: /speak-zhouli <文本>\n例如: /speak-zhouli 今天天气真好")
            return
        try:
            import importlib
            _sz = importlib.import_module("skill.speak_zhouli")
            rewritten = _sz.rewrite_zhouli(text_to_rewrite)
            if rewritten.startswith("ERROR:"):
                await _send_reply(event, f"改写失败: {rewritten}")
            else:
                img_path = Path(__file__).parent / "assets" / "大周礼时代.jpg"
                img_cq = f"[CQ:image,file=file:///{img_path.as_posix()}]"
                await _send_reply(event, f"{rewritten}\n{img_cq}")
        except Exception as e:
            logger.error("speak-zhouli 出错", exc_info=True)
            await _send_reply(event, f"改写出错: {e}")
        return

    try:
        ai = _get_ai()
        cid = f"group:{event.group_id}" if is_group else f"private:{event.user_id}"
        logger.info("Sending to AI (cid=%s): %s", cid, text)

        async def _on_tool_start(tool_name: str):
            if tool_name.startswith("download"):
                await _send_reply(event, f"⏳ 正在{tool_name.replace('_', ' ')}，请稍候...")

        reply, files = await ai.handle(text, user_id=cid, on_tool_start=_on_tool_start)
        logger.info("AI reply (first 200): %s", reply[:200] if reply else "None")
        await _send_reply(event, reply)

        # AI 回复自动 TTS 语音（限 500 字，失败不影响文字）
        has_wav = any(f.lower().endswith(".wav") for f in files)
        if not has_wav and reply and len(reply) <= 500 and getattr(handle_tts_switch, "_ai_tts_enabled", True):
            try:
                await tts_speak_text(reply, event, bot)
            except Exception:
                logger.warning("AI reply TTS failed", exc_info=True)

        for f in files:
            ext = Path(f).suffix.lower()
            if ext in (".mp4", ".mkv", ".webm", ".flv", ".avi"):
                await _send_video(event, f)
            elif ext == ".wav":
                cq = f"[CQ:record,file=file:///{Path(f).as_posix()}]"
                await bot.send(event, Message(cq))
                Path(f).unlink(missing_ok=True)
            else:
                await _send_file(event, f)
        logger.info("AI reply sent, files=%d", len(files))
    except ValueError as e:
        logger.warning("AI not available: %s", e)
        if "OPENAI_API_KEY" in str(e):
            await _send_reply(event, "❌ AI 功能未配置，请在 .env 中设置 OPENAI_API_KEY")
        else:
            await _send_reply(event, f"❌ AI 初始化失败: {e}")
        logger.info("Fallback reply sent")
    except Exception as e:
        logger.error("AI handler error", exc_info=True)
        await _send_reply(event, f"抱歉，处理出错: {e}\n输入 /help 查看可用命令。")
        logger.info("Error reply sent")


# ── Main ─────────────────────────────────────────────────────────

@bot.server_app.before_serving
async def _startup_mcp():
    global _mcp_manager, _ai_handler
    logger.info("启动 MCP 服务...")
    _mcp_manager = McpManager()
    await _mcp_manager.start()
    _ai_handler = AIHandler(_mcp_manager)
    from tts.commands import set_mcp
    set_mcp(_mcp_manager)
    logger.info("MCP 服务启动完成")

    await tts_mgr.start()
    if tts_mgr.current_persona():
        system_prompt = tts_mgr.current_persona().get("system_prompt")
        if not system_prompt:
            system_prompt = tts_mgr._load_system_prompt(tts_mgr.current_name)
        from core.ai_handler import set_system_prompt
        set_system_prompt(system_prompt)


@bot.server_app.after_serving
async def _shutdown():
    pass


def main():
    host = os.environ.get("BOT_HOST", "127.0.0.1")
    port = int(os.environ.get("BOT_PORT", "8080"))

    logger.info("=" * 50)
    logger.info("QQ Bot 启动")
    logger.info("WebSocket 服务: %s:%s", host, port)
    logger.info("NapCatQQ 配置: ws://%s:%s/ws/", host, port)
    logger.info("OpenAI API Key: %s", "已设置" if os.environ.get("OPENAI_API_KEY") else "未设置")
    logger.info("OpenAI Model: %s", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    logger.info("OpenAI Base URL: %s", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    logger.info("=" * 50)
    logger.info("Bot started. Waiting for messages...")

    bot.run(host=host, port=port, startup_timeout=120)


if __name__ == "__main__":
    main()
