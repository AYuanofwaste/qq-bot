# QQ Bot — 东雪莲/永雏塔菲（纯ai写，不喜勿喷）

基于 **NapCatQQ (OneBot v11)**，集成 **AI 聊天（工具调用）**、**Bert-VITS2 v2.3 TTS 语音合成**、**JMComic/Pixiv/Bilibili** 服务的多模块 QQ 机器人。

## 功能特性

| 模块 | 能力 | 协议 |
|------|------|------|
| **AI 聊天** | 东雪莲/永雏塔菲人设（动态切换），OpenAI SDK 驱动工具调用 | OpenAI API |
| **TTS 语音合成** | Bert-VITS2 v2.3，中日英三语 `AUTO` 分段，人设/模型联动切换 | MCP stdio |
| **Pixiv** | 搜索、排行榜、详情、相关推荐、热门标签、下载 | MCP stdio |
| **JMComic** | 按 ID 下载漫画并转为 PDF | MCP stdio |
| **Bilibili** | 视频下载（自动压缩适配 QQ）、直播状态查询 | MCP stdio |
| **游戏新闻** | ali213 国内 / VGC/ResetEra/Insider/Steam 国外（DeepSeek 翻译） | 线程池 |
| **大周礼腔** | `/speak-zhouli` 手动命令改写 AI 回复为周礼腔 | OpenAI 直调 |

## 快速开始

### 1. 获取代码

```bash
git clone <仓库地址> qq-bot
cd qq-bot
```

或直接将 `qq-bot/` 目录复制到目标位置。

### 2. 安装 Python 环境

```powershell
conda create -n qq-bot python=3.11
conda activate qq-bot
```

> **务必 Python 3.11**。`pyopenjtalk-prebuilt` 只有 cp311 wheel，3.12/3.13 无对应包。

### 3. 安装 CUDA（如无可跳过，TTS 会用 CPU）

确认 PyTorch 能调用 GPU：

```powershell
nvidia-smi                        # 查看 CUDA 版本（推荐 12.4+）
```

如果 `nvidia-smi` 提示命令不存在，说明没有 NVIDIA 驱动，请在 [NVIDIA 官网](https://www.nvidia.com/Download/index.aspx) 安装。

### 4. 安装核心依赖

```powershell
# 4a. 先降 setuptools（pyopenjtalk 需要 <72）
pip install "setuptools<72"

# 4b. PyTorch（CUDA 12.4 版，换版本改 cu118/cu121）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# 4c. 项目全部依赖
pip install -r requirements.txt

# 4d. 验证关键包
python -c "
import torch; print('Torch', torch.__version__, 'CUDA:', torch.cuda.is_available())
import transformers; print('Transformers', transformers.__version__)
import pyopenjtalk; print('pyopenjtalk', pyopenjtalk.__version__)
"
```

> 国内慢可加 `-i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`。  
> 如 Torch 显示 CUDA: False，TTS 会自动切 CPU（慢 5-10 倍，但仍可用）。

### 5. 安装 FFmpeg

B站视频压缩和 Pixiv ugoira→GIF 需要：

```powershell
winget install "FFmpeg (Essentials Build)"    # 或从 https://ffmpeg.org/download.html 手动安装
ffmpeg -version                                # 确认安装成功
```

### 6. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env`，填入你的 API Key（各字段说明见下方「配置」章节）。最少只需填 `OPENAI_API_KEY` 即可运行 AI 聊天。

### 7. 安装 NapCatQQ

下载 [NapCatQQ](https://napneko.github.io/guide/) 并解压，配置反向 WebSocket（见下方「配置」章节），启动后记住端口号。

```powershell
# 启动 NapCatQQ（假设解压到 D:\NapCatQQ）
cd D:\NapCatQQ
napcat.bat
```

### 8. 启动机器人

```powershell
python bot.py
```

看到日志 `"Bot started. Waiting for messages..."` 即启动成功。首次启动会顺序拉起 4 个 MCP 服务，TTS 首次加载约 58s。

## 项目结构

```
qq-bot/
├── bot.py                       # 主入口，单 handler 消息路由
├── .env                         # ⚠️ 环境变量（API Key 等，已 gitignore）
├── requirements.txt             # Python 依赖
├── opencode.jsonc               # opencode MCP 注册配置（4 服务）
│
├── core/
│   ├── ai_handler.py            # OpenAI 聊天 + 4 个 AI 工具（TTS/搜索/下载）
│   └── helpers.py               # 通用工具函数
│
├── mcp_client/
│   └── client.py                # MCP 客户端封装（McpManager，4 session）
│
├── tts/                         # Bert-VITS2 v2.3 推理（MCP 封装）
│   ├── mcp_server.py            # MCP 薄壳，lifespan 管理 HTTP 子进程
│   ├── server.py                # FastAPI TTS HTTP 引擎（uvicorn）
│   ├── __init__.py              # TTSManager：人设管理，不启动子进程
│   ├── commands.py              # AI 工具函数（synthesize/switch/language，通过 MCP 调用）
│   ├── defaults.py              # TTS_DEFAULTS 统一参数
│   ├── personae.yml             # 人设配置（model_id / speaker / prompt）
│   ├── config.yml               # 服务配置（端口、模型列表、翻译凭据）
│   ├── model/
│   │   ├── azuma/               # 东雪莲模型 (azuma.pth ~728MB)
│   │   └── taffy/               # 塔菲模型 (taffy.pth ~728MB)
│   ├── text/ tools/             # 文本处理、翻译、日志工具
│   └── bert/                      # BERT 模型权重（首次启动自动下载 ~3GB）
│
├── bilibili/
│   ├── server.py                # B站 MCP 服务（视频下载 + 直播查询）
│   ├── dl.py                    # yt-dlp 下载 + FFmpeg 压缩
│   ├── live.py                  # 关注列表直播状态
│   └── downloads/               # 视频下载目录（已 gitignore）
│
├── jmcomic/
│   └── server.py                # JMComic MCP 服务（下载 → PDF）
│
├── pixiv/
│   ├── server.py                # Pixiv MCP 服务（搜索/排行/下载）
│   ├── auth.py                  # OAuth PKCE / PHPSESSID 双模式
│   ├── client.py                # pixivpy3 + web ajax 双客户端
│   └── downloader.py            # 异步下载 + ugoira → GIF
│
├── skill/
│   └── speak_zhouli/            # /speak-zhouli 手动命令（非 MCP）
│       └── __init__.py          # 直接调用 OpenAI 改写
│
├── prompt/                      # 人设 SYSTEM_PROMPT
│   ├── 提示_azuma.txt
│   └── 提示_taffy.txt
│
├── scripts/
│   ├── set_bilibili_cookies.bat  # B站 cookies 交互式设置入口
│   └── set_bilibili_cookies.ps1  # 解析 raw Cookie → Netscape 格式
│
└── assets/
    └── 大周礼时代.jpg            # speak-zhouli 回复附带图片
```

## 架构

```
┌──────────┐     WebSocket      ┌──────────┐     MCP stdio     ┌──────────────────────┐
│ NapCatQQ │ ←──────────────→ │ bot.py   │ ←────────────→ │ jmcomic/server.py     │
└──────────┘                    │ (main)  │                  └──────────────────────┘
                                │          │     MCP stdio     ┌──────────────────────┐
                                │          │ ←────────────→ │ pixiv/server.py       │
                                │          │                  └──────────────────────┘
                                │          │     MCP stdio     ┌──────────────────────┐
                                │          │ ←────────────→ │ bilibili/server.py    │
                                │          │                  └──────────────────────┘
                                │          │     MCP stdio     ┌──────────────────────┐
                                │          │ ←────────────→ │ tts/mcp_server.py      │
                                │          │                  │   lifespan 管理      │
                                │          │                  │   └→ tts/server.py   │
                                │          │                  │      (HTTP :9880)    │
                                │          │                  └──────────────────────┘
                                │          │
                                │          │     直调 OpenAI     ┌──────────────────────┐
                                │          │ ←──────────────── │ speak_zhouli 改写     │
                                │          │                  └──────────────────────┘
                                └────┬─────┘
                                     │ ThreadPool
                                     ▼
                           ┌──────────────────────┐
                           │ news / live 同步任务   │
                           └──────────────────────┘
```

- **NapCatQQ**：NTQQ 无头 Bot 框架，提供 OneBot v11 WebSocket
- **bot.py**：单 handler 分发，AI 对话 + 工具调用；`before_serving` 依次启动 4 个 MCP 服务
- **4 个 MCP 服务**：jmcomic、pixiv、bilibili、tts，通过 `opencode.jsonc` 注册、`McpManager` 管理
- **TTS**：`tts/mcp_server.py` 薄壳封装 `tts/server.py` HTTP 引擎，对外暴露 `synthesize` 工具
- **speak-zhouli**：不走 MCP，`bot.py` 通过 `importlib.import_module` 直接调用 OpenAI 改写

## 环境要求

### 硬件

| 项目 | 最低 | 推荐 |
|------|------|------|
| GPU 显存 | 6GB（CPU 推理） | **8GB+**（GPU 推理约 5-7GB） |
| 磁盘 | 15GB 空闲 | 20GB+（模型文件 + 依赖 ~10GB） |
| 内存 | 16GB | 32GB |

### 软件

| 项目 | 版本要求 | 安装方式 |
|------|----------|----------|
| OS | Windows 10/11 64bit | — |
| Python | **3.11**（3.12+ 无 pyopenjtalk wheel） | conda / 官网 |
| CUDA | 11.8+（推荐 12.4） | `nvidia-smi` 查看版本后安装 |
| [NapCatQQ](https://napneko.github.io/) | 最新 | 下载解压即用 |
| FFmpeg | 最新 | `winget install "FFmpeg (Essentials Build)"` |

## 配置

### ⚠️ 安全警告

> 以下值均为示例，请替换为你的真实密钥。`.env` 已在 `.gitignore` 中排除。

### 1. 创建 `.env`

```ini
# ── Bot 基础 ──
BOT_HOST=127.0.0.1
BOT_PORT=8080
BOT_TOKEN=

# ── AI 聊天（必填） ──
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=                    # 默认 OpenAI，换 DeepSeek 填 https://api.deepseek.com
OPENAI_MODEL=                       # 默认 gpt-4o-mini

# ── Pixiv（推荐 OAuth） ──
PIXIV_PHPSESSID=your_phpsessid
PIXIV_REFRESH_TOKEN=your_refresh_token

# ── B站（可选） ──
BILIBILI_COOKIES_FILE=              # 默认 qq-bot/bilibili/bilibili_cookies.txt

# ── 百度翻译（TTS 中日英自动翻译，置空则关闭） ──
BAIDU_APP_ID=your_baidu_app_id
BAIDU_SECRET_KEY=your_baidu_secret
```

### 2. 安装 NapCatQQ

参考 [官方文档](https://napneko.github.io/guide/) 安装。配置反向 WebSocket：

```json
{
  "network": {
    "websocketClients": [{
      "name": "QQBot",
      "enable": true,
      "url": "ws://127.0.0.1:8080/ws/",
      "messagePostFormat": "array",
      "reportSelfMessage": false,
      "reconnectInterval": 5000,
      "token": "",
      "heartInterval": 30000
    }]
  }
}
```

### 3. 获取 Pixiv Token（推荐 OAuth）

```bash
cd qq-bot/pixiv
python -c "from auth import run_pkce_flow; run_pkce_flow()"
```

按提示在浏览器登录 Pixiv 并授权，Token 自动写入 `.env`。

如果浏览器没有跳转到 `pixiv://` 协议链接，打开 F12 → Network 栏，筛选 `callback` 或 `pixiv://`，找到带 `code=` 参数的请求，复制完整 URL 粘贴回终端。

### 4. 设置 B站 Cookies

运行交互脚本，从浏览器 F12 → Network 复制 Cookie 值粘贴：

```bash
scripts\set_bilibili_cookies.bat
```

### 5. 启动

```bash
# 终端 1：启动 Bot
cd qq-bot
python bot.py

# 终端 2：启动 NapCatQQ
cd NapCatQQ目录
napcat.bat
```

Bot 启动时自动拉起 4 个 MCP 服务（jmcomic → pixiv → bilibili → tts），首次 TTS 加载约 58s。

## 依赖说明

| 包 | 用途 | 版本约束 |
|---|---|---|
| `torch>=2.0.0` | 深度学习 | 需 CUDA 版本 |
| `transformers<5` | BERT 模型 | **务必 <5**，5.x 要求 torch>=2.6 |
| `tokenizers<0.14` | 分词器 | 与 transformers 4.30.x 兼容 |
| `numpy<2` | 科学计算 | 与 pyopenjtalk .pyd 兼容 |
| `setuptools<72` | pkg_resources | pyopenjtalk 需要 |
| `pyopenjtalk-prebuilt` | 日语 TTS 前端 | cp311 wheel |
| `langid` | 语种识别 | TTS `language="AUTO"` 必需 |
| `mcp>=1.0.0` | MCP 客户端/服务端 | 需 Python>=3.10 |

## 命令列表

### 基础命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/forget` | 清空 AI 对话记忆 |
| `/speak-zhouli <文本>` | 改写为大周礼腔调 |
| `/news` | 游戏新闻菜单 |
| `/国内新闻` | ali213 最新 5 条（带图） |
| `/国外新闻` | 国外新闻源子菜单 |
| `/vgc` / `/resetera` / `/insider` / `/steam` | 各源最新 5 条（带中文翻译） |

### AI 聊天

| 方式 | 说明 |
|------|------|
| 群聊 `@机器人 <消息>` | AI 对话 + 自动工具调用 |
| 私聊 `<任意消息>` | 直接 AI 对话 |
| `@机器人 说一下<文本>` | AI 回复 + TTS 语音 |
| `@机器人 切换中文` | 切换 TTS 默认语言 |
| `@机器人 开启/关闭 AI 语音` | AI 自动语音开关 |
| `@机器人 切换东雪莲/塔菲` | 切换人设 + TTS 模型 |

AI 自动识别意图调用工具：
- "帮我搜一下碧蓝档案的图" → Pixiv 搜索
- "今天P站排行榜" → 排行榜
- "帮我下这个漫画 JM123456" → 下载 JM 漫画
- "你好" → 语音合成回复

## TTS 服务

### 架构

```
bot.py ──MCP stdio──→ tts/mcp_server.py ──子进程──→ tts/server.py (HTTP :9880)
```

- `tts/mcp_server.py`：FastMCP 薄壳，`lifespan` 启动/关闭 `server.py` 子进程
- `tts/server.py`：FastAPI + uvicorn，单 worker，首次请求加载模型
- 通信：MCP `synthesize` 工具 → httpx GET `127.0.0.1:9880/voice` → 返回 WAV 路径

### TTS 配置 (tts/config.yml)

```yaml
server:
  port: 9880
  device: "cuda"
  models:
    - model: "model\\azuma\\azuma.pth"
      config: "model\\azuma\\config.json"
      device: "cuda"
      language: "ZH"

translate:
  app_key: ""            # 由 .env BAIDU_APP_ID 覆盖
  secret_key: ""         # 由 .env BAIDU_SECRET_KEY 覆盖
```

### TTS 默认参数 (tts/defaults.py)

```python
TTS_DEFAULTS = {
    "sdp_ratio": 0.5,    # SDP 比例
    "noise": 0.6,        # 感情噪声
    "noisew": 0.9,       # 音素噪声
    "length": 0.9,       # 语速
}
```

### 人设配置 (tts/personae.yml)

```yaml
Azuma:
  model_id: 0
  model_path: "qq-bot\\tts\\model\\azuma\\azuma.pth"
  config_path: "qq-bot\\tts\\model\\azuma\\config.json"
  speaker_name: "Azuma"
  language: "ZH"
  system_prompt_file: "qq-bot\\prompt\\提示_azuma.txt"
```

### 添加新角色

1. 训练 Bert-VITS2 v2.3 模型，复制 `G_*.pth` 到 `tts/model/<角色名>/`
2. 复制 `config.json` 到同目录
3. 创建 `prompt/提示_<角色名>.txt`
4. 在 `tts/personae.yml` 添加条目，统一 `model_id` 序号
5. 在 `tts/config.yml` 添加模型配置
6. 重启 bot

## 常见问题

### Q: pyopenjtalk 导入报错

```powershell
pip install "setuptools<72"
pip install "numpy<2"
```

### Q: transformers 报需要 torch>=2.6

```powershell
pip install "transformers<5"
```

### Q: TTS 返回 Internal Server Error 500

`langid` 未安装，`language="AUTO"` 时 `classify_language()` 崩溃：

```powershell
pip install langid
```

### Q: TTS 请求超时

首次请求需加载模型到 GPU，耗时约 58s。预热即可（后续请求 <3s）。  
若经常超时请确认显存 ≥8GB。

### Q: HFValidationError

使用 `local_files_only=True` + 绝对路径调用 BERT 模型，或降级 transformers。

---

## 技术细节

### MCP 架构

4 个 MCP 服务在 `opencode.jsonc` 注册，`bot.py` `before_serving` 通过 `McpManager` 顺序拉起：

1. `python jmcomic/server.py`
2. `python pixiv/server.py`
3. `python bilibili/server.py`
4. `python tts/mcp_server.py`（内部再起 `python server.py` HTTP 引擎）

通信：MCP stdio（JSON-RPC over stdin/stdout），`AIHandler` 自动映射 AI 工具调用到 MCP 工具。

### TTS 多语种

- `language="AUTO"` + `auto_split=True` 启用 Bert-VITS2 内置 `split_by_language`，依赖 `langid` 做语种识别
- 中英混合文本自动分段（ZH/EN/JP），每段使用对应 BERT 模型提取语义
- 翻译使用百度翻译 API（凭据在 `.env` 中配置），不走 OpenAI

### TTS 子进程

- 使用 `sys.executable`（与 bot.py 同一 Python 环境），不依赖 `D:\Bert-VITS2-v2.3\venv`
- 子进程 cwd = `tts/` 目录（旧代码大量 `./bert/` 等相对路径）
- HTTP 通信绕过系统代理（`httpx.HTTPTransport()` / `httpx.AsyncHTTPTransport()`）

### AI 人设

- 通过 AI 自然语言（如「切换东雪莲」）动态切换人设，同时切换 TTS 模型 + SYSTEM_PROMPT
- 4 个 AI 工具（`synthesize_tts`、`switch_tts_language`、`toggle_ai_tts`、`switch_persona`）在 `core/ai_handler.py` 定义
- 使用 `importlib.import_module("skill.speak_zhouli")` 直接调用入口，不走 MCP
