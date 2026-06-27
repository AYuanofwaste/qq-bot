"""Speak-Zhouli — 将现代中文改写成'大周礼时代'的白话翻译腔风格。"""

import os
from pathlib import Path

from openai import OpenAI

SKILL_DIR = Path(__file__).resolve().parent
SKILL_MD = SKILL_DIR / "SKILL.md"
SYSTEM_PROMPT = SKILL_MD.read_text(encoding="utf-8")

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")

if not API_KEY:
    env_path = SKILL_DIR.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip("\"'")
            elif line.startswith("OPENAI_BASE_URL="):
                BASE_URL = line.split("=", 1)[1].strip("\"'")

_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def rewrite_zhouli(text: str) -> str:
    if not text.strip():
        return "ERROR: 输入文本不能为空"
    try:
        resp = _client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"ERROR: {e}"
