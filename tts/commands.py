import asyncio
import time
import httpx
import logging
import os
import re
from pathlib import Path

from aiocqhttp import Event
from aiocqhttp.message import Message

from tts.defaults import TTS_DEFAULTS
from tts import tts_mgr

logger = logging.getLogger("qq-bot.tts")

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_OUTPUT = BASE_DIR / "tts_output"
TTS_API = os.environ.get("TTS_API", "http://127.0.0.1:9880")

_mcp: "McpManager | None" = None


def set_mcp(mcp: "McpManager"):
    global _mcp
    _mcp = mcp


def _get_mcp():
    if _mcp is None:
        raise RuntimeError("MCP manager not set (call set_mcp first)")
    return _mcp


def _parse_tts_opts(args: list[str]) -> tuple[str, dict]:
    text_parts = []
    opts = {}
    i = 0
    while i < len(args):
        if args[i] in ("-n", "--noise") and i + 1 < len(args):
            opts["noise"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-l", "--length") and i + 1 < len(args):
            opts["length"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-e", "--emotion") and i + 1 < len(args):
            opts["emotion"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-s", "--sdp") and i + 1 < len(args):
            opts["sdp_ratio"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-w", "--noisew") and i + 1 < len(args):
            opts["noisew"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-p", "--promptw") and i + 1 < len(args):
            opts["promptw"] = float(args[i + 1])
            i += 2
        elif args[i] in ("-j", "--jp"):
            opts["language"] = "JP"
            i += 1
        elif args[i] in ("-z", "--zh"):
            opts["language"] = "ZH"
            i += 1
        elif args[i] in ("-e", "--en"):
            opts["language"] = "EN"
            i += 1
        elif args[i] in ("-t", "--translate"):
            opts["translate"] = True
            i += 1
        else:
            text_parts.append(args[i])
            i += 1
    return " ".join(text_parts), opts


async def _translate_text(text: str, target_lang: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{TTS_API}/tools/translate",
                params={"text": text, "to_lang": target_lang},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"翻译接口返回 {resp.status_code}")
            result = resp.json()
            if result.get("status") != 0:
                raise RuntimeError(result.get("detail", "翻译失败"))
            return result["data"]
    except httpx.ConnectError:
        raise RuntimeError("无法连接 TTS 服务（翻译接口）")
    except Exception as e:
        raise RuntimeError(f"翻译失败: {e}")


def _filter_tts_text(raw: str) -> str:
    segments = raw.split("\n\n")
    cleaned = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        seg = re.sub(r"（[^）]*）", "", seg).strip()
        if seg:
            cleaned.append(seg)
    return " ".join(cleaned)


def _lang_name(lang: str) -> str:
    return {"ZH": "中文", "JP": "日语", "EN": "英语"}.get(lang, lang)


async def handle_tts_switch(args: list[str], event: Event, bot) -> str:
    _tts_default_lang = getattr(handle_tts_switch, "_default_lang", "ZH")
    _ai_tts_enabled = getattr(handle_tts_switch, "_ai_tts_enabled", True)
    if not args:
        status = "开" if _ai_tts_enabled else "关"
        return f"用法: /tts <zh|jp|en|on|off>\n当前语言: {_lang_name(_tts_default_lang)} | AI自动语音: {status}"
    cmd = args[0].lower()
    if cmd in ("on", "off"):
        handle_tts_switch._ai_tts_enabled = (cmd == "on")
        return f"AI 自动语音已{'开启' if cmd == 'on' else '关闭'}"
    if cmd not in ("zh", "jp", "en"):
        status = "开" if _ai_tts_enabled else "关"
        return f"用法: /tts <zh|jp|en|on|off>\n当前语言: {_lang_name(_tts_default_lang)} | AI自动语音: {status}"
    target = cmd.upper()
    if target == _tts_default_lang:
        return f"已经是{_lang_name(target)}模式了"
    handle_tts_switch._default_lang = target
    return f"已切换为{_lang_name(target)}模式"


async def handle_speak(args: list[str], event: Event, bot) -> str:
    _tts_default_lang = getattr(handle_tts_switch, "_default_lang", "ZH")

    if not args:
        return (
            "用法: /speak <文本> [选项]\n"
            "选项:\n"
            "  -n, --noise <值>     噪声 (默认 %s)\n"
            "  -l, --length <值>    语速 (默认 %s)\n"
            "  -e, --emotion <值>   情感强度 0-1\n"
            "  -s, --sdp <值>       SDP 比例 (默认 %s)\n"
            "  -w, --noisew <值>    噪声 W (默认 %s)\n"
            "  -p, --promptw <值>   提示权重 (默认 0.7)\n"
            "  -j, --jp            日语模式\n"
            "  -z, --zh            中文模式\n"
            "  -e, --en            英语模式\n"
            "  -t, --translate     中译日（Bert-VITS2 自带）后再朗读\n"
            "示例:\n"
            "  /speak 晚上好呀\n"
            "  /speak hello world -e\n"
            "  /speak こんにちは -j\n"
            "  /speak 晚上好呀 -t\n"
            "  /speak 晚上好呀 -n 0.3 -l 1.1 -e 0.5"
        ) % (
            TTS_DEFAULTS["noise"],
            TTS_DEFAULTS["length"],
            TTS_DEFAULTS["sdp_ratio"],
            TTS_DEFAULTS["noisew"],
        )

    text, opts = _parse_tts_opts(args)
    text = _filter_tts_text(text)
    if not text:
        return "❌ 文本不能为空（动作描写已过滤）"

    text = re.sub(r'\s+(-t|--translate)\s*$', '', text).strip()
    text = re.sub(r'\s+(-j|--jp)\s*$', '', text).strip()
    text = re.sub(r'\s+(-z|--zh)\s*$', '', text).strip()
    text = re.sub(r'\s+(-e|--en)\s*$', '', text).strip()

    TTS_OUTPUT.mkdir(parents=True, exist_ok=True)

    translate = opts.get("translate") or bool(re.search(r'(^|\s)(-t|--translate)(\s|$)', " ".join(args)))
    language = opts.get("language", _tts_default_lang)
    if translate or (language == "JP" and re.search(r'[\u4e00-\u9fff]', text) and not re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text)):
        if not translate:
            logger.info("检测到中文文本，自动翻译: %s", text)
        try:
            translated = await _translate_text(text, "jp")
            logger.info("翻译结果: %s -> %s", text, translated)
            text = translated
        except Exception as e:
            return f"❌ 翻译失败: {e}"
        language = "JP"
    if language == "EN" and re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text):
        logger.info("检测到非英文文本，自动翻译: %s", text)
        try:
            translated = await _translate_text(text, "en")
            logger.info("翻译结果: %s -> %s", text, translated)
            text = translated
        except Exception as e:
            return f"❌ 翻译失败: {e}"

    params = {
        "text": text,
        "model_id": tts_mgr.model_id,
        "speaker_name": tts_mgr.speaker_name,
        "sdp_ratio": opts.get("sdp_ratio", TTS_DEFAULTS["sdp_ratio"]),
        "noise": opts.get("noise", TTS_DEFAULTS["noise"]),
        "noisew": opts.get("noisew", TTS_DEFAULTS["noisew"]),
        "length": opts.get("length", TTS_DEFAULTS["length"]),
        "language": "AUTO",
        "auto_split": True,
    }
    if "emotion" in opts:
        params["emotion"] = opts["emotion"]
    if "promptw" in opts:
        params["promptw"] = opts["promptw"]

    mcp = _get_mcp()
    try:
        wav_path_str = await mcp.synthesize(
            text=text, model_id=tts_mgr.model_id,
            speaker_name=tts_mgr.speaker_name,
            sdp_ratio=opts.get("sdp_ratio", TTS_DEFAULTS["sdp_ratio"]),
            noise=opts.get("noise", TTS_DEFAULTS["noise"]),
            noisew=opts.get("noisew", TTS_DEFAULTS["noisew"]),
            length=opts.get("length", TTS_DEFAULTS["length"]),
            language="AUTO",
            auto_split=True,
        )
    except RuntimeError as e:
        return f"❌ TTS 服务未就绪: {e}"
    except Exception as e:
        return f"❌ TTS 请求失败: {e}"

    if wav_path_str.startswith("ERROR:"):
        return f"❌ {wav_path_str[6:]}"

    wav_path = Path(wav_path_str)
    logger.info("TTS 生成成功: %s (%.1fKB)", wav_path, wav_path.stat().st_size / 1024)

    cq = f"[CQ:record,file=file:///{wav_path.as_posix()}]"
    await bot.send(event, Message(cq))
    wav_path.unlink(missing_ok=True)
    return f"🔊 关注{tts_mgr.current_name}谢谢喵～"


async def tts_speak_text(text: str, event: Event, bot) -> bool:
    """AI 回复自动 TTS 语音合成（含翻译）"""
    text = _filter_tts_text(text)
    if not text:
        return False

    _tts_default_lang = getattr(handle_tts_switch, "_default_lang", "ZH")
    language = _tts_default_lang

    if language == "JP" and re.search(r'[\u4e00-\u9fff]', text) and not re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
        try:
            translated = await _translate_text(text, "jp")
            logger.info("TTS auto translate: %s -> %s", text, translated)
            text = translated
        except Exception:
            logger.warning("TTS translate to JP failed, using original text")
    elif language == "EN" and re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text):
        try:
            translated = await _translate_text(text, "en")
            logger.info("TTS auto translate: %s -> %s", text, translated)
            text = translated
        except Exception:
            logger.warning("TTS translate to EN failed, using original text")

    mcp = _get_mcp()
    try:
        wav_path_str = await mcp.synthesize(
            text=text, model_id=tts_mgr.model_id,
            speaker_name=tts_mgr.speaker_name,
            sdp_ratio=TTS_DEFAULTS["sdp_ratio"],
            noise=TTS_DEFAULTS["noise"],
            noisew=TTS_DEFAULTS["noisew"],
            length=TTS_DEFAULTS["length"],
            language="AUTO", auto_split=True,
        )
    except Exception as e:
        logger.warning("TTS API request failed: %s", e)
        return False

    if wav_path_str.startswith("ERROR:"):
        logger.warning("TTS API error: %s", wav_path_str)
        return False

    wav_path = Path(wav_path_str)
    logger.info("AI reply TTS: %s (%.1fKB)", wav_path, wav_path.stat().st_size / 1024)

    cq = f"[CQ:record,file=file:///{wav_path.as_posix()}]"
    await bot.send(event, Message(cq))
    wav_path.unlink(missing_ok=True)
    return True


async def handle_switch(args: list[str], event: Event, bot) -> str:
    from tts import tts_mgr
    from core.ai_handler import set_system_prompt

    if not args:
        names = " / ".join(tts_mgr.list_personae())
        return f"用法: /switch <角色名>\n可用角色: {names}\n当前: {tts_mgr.current_name}"

    name = args[0].capitalize()
    if name not in tts_mgr.list_personae():
        names = " / ".join(tts_mgr.list_personae())
        return f"❌ 未知角色: {name}\n可用角色: {names}"

    system_prompt = tts_mgr.switch_persona(name)
    set_system_prompt(system_prompt)
    return f"✅ 已切换为 {name}\n🔊 关注{name}谢谢喵～"
