import logging
import os
from pathlib import Path

logger = logging.getLogger("qq-bot.tts")

_THIS_DIR = Path(__file__).resolve().parent
_QQ_BOT_DIR = _THIS_DIR.parent
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", str(_QQ_BOT_DIR.parent)))


class TTSManager:
    def __init__(self):
        self._personae: dict[str, dict] = {}
        self._current: str = "Azuma"
        self._process = None
        self._ready = False
        self._tts_dir = Path(__file__).parent
        self._personae_path = self._tts_dir / "personae.yml"
        self._server_script = self._tts_dir / "server.py"
        self._config_path = self._tts_dir / "config.yml"

    def _load_personae(self):
        import yaml
        with open(self._personae_path, encoding="utf-8") as f:
            self._personae = yaml.safe_load(f)

    async def start(self):
        self._load_personae()
        logger.info("TTS: 加载 %d 个人设", len(self._personae))
        # TTS server 由 MCP 管理，不再启动子进程
        logger.info("TTS: 等待 MCP 连接...")

    async def stop(self):
        pass

    def current_persona(self) -> dict:
        return self._personae.get(self._current, {})

    def list_personae(self) -> list[str]:
        return list(self._personae.keys())

    def switch_persona(self, name: str) -> str:
        if name not in self._personae:
            raise ValueError(f"未知角色: {name}，可用: {list(self._personae.keys())}")
        self._current = name
        return self._load_system_prompt(name)

    def _load_system_prompt(self, name: str) -> str:
        path_str = self._personae[name]["system_prompt_file"]
        if not os.path.isabs(path_str):
            path = PROJECT_ROOT / path_str
        else:
            path = Path(path_str)
        with open(path, encoding="utf-8") as f:
            return f.read()

    @property
    def current_name(self) -> str:
        return self._current

    @property
    def speaker_name(self) -> str:
        return self._personae[self._current]["speaker_name"]

    @property
    def model_id(self) -> int:
        return self._personae[self._current].get("model_id", 0)


tts_mgr = TTSManager()
