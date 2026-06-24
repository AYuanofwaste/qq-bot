# QQ Bot — 永雏塔菲

将 **JMComic、Pixiv、Bilibili、AI 聊天、游戏新闻** 集成到 QQ 机器人的多模块 Bot，通过 NapCatQQ (OneBot v11) 连接。

## 功能特性

| 模块 | 能力 |
|------|------|
| **AI 聊天** | 永雏塔菲人设，自然语言驱动工具调用（搜索/下载 Pixiv、JM、B站） |
| **Pixiv** | 搜索插画、排行榜、详情、相关推荐、热门标签、下载（单图/多页/Ugoira→GIF） |
| **JMComic** | 按 ID 下载漫画并转为 PDF |
| **Bilibili** | 视频下载（自动压缩适配 QQ）、直播列表查询 |
| **游戏新闻** | ali213 国内、VGC/ResetEra/Insider/Steam 国外（带 DeepSeek 中文翻译） |

## 快速开始

```bash
cd qq-bot
pip install -r requirements.txt
cp .env.example .env        # 复制并编辑配置
python bot.py               # 启动机器人
```

> 还需要安装并启动 [NapCatQQ](https://napneko.github.io/guide/) 以连接 QQ。

## 项目结构

```
qq-bot/
├── bot.py                    # 主入口，WebSocket 消息路由
├── .env                      # ⚠️ 环境变量（API Key 等敏感信息，已 gitignore）
├── requirements.txt          # Python 依赖
├── opencode.jsonc            # opencode MCP 注册配置
│
├── core/
│   ├── ai_handler.py         # OpenAI/DeepSeek 聊天 + 工具调用（塔菲人设）
│   └── helpers.py            # 通用工具函数
│
├── bilibili/
│   ├── dl.py                 # B站视频下载（yt-dlp）
│   ├── live.py               # B站直播查询（关注列表+直播状态）
│   ├── test_live.py          # 直播模块测试脚本
│   └── downloads/            # 视频下载目录（已 gitignore）
│
├── news/
│   ├── domestic.py           # 国内游戏新闻（ali213）
│   └── global_.py            # 国外游戏新闻（VGC/ResetEra/Insider/Steam + DeepSeek 翻译）
│
├── mcp_client/
│   └── client.py             # MCP 客户端封装（McpManager），管理子进程
│
├── jmcomic/
│   ├── server.py             # JMComic MCP 服务器（stdio 传输，下载漫画→PDF）
│   └── output/               # PDF 输出目录（已 gitignore）
│
└── pixiv/
    ├── server.py             # Pixiv MCP 服务器（stdio 传输，搜索/浏览/下载）
    ├── auth.py               # Pixiv OAuth 认证（PKCE 流程 + PHPSESSID 支持）
    ├── client.py             # Pixiv API 客户端（pixivpy3 + web ajax 双模式）
    ├── downloader.py         # 异步下载管理器（ThreadPool + ugoira→GIF）
    └── downloads/            # 插画下载目录（已 gitignore）
```

## 架构

```
┌──────────┐     WebSocket      ┌─────────┐     MCP stdio     ┌──────────────────┐
│ QQ 客户端 │ ←─────────────→ │ bot.py   │ ←────────────→ │ jmcomic/server.py │
└──────────┘                    │         │                  └──────────────────┘
                                │         │     MCP stdio     ┌──────────────────┐
                                │         │ ←────────────→ │ pixiv/server.py   │
                                │         │                  └──────────────────┘
                                └───┬─────┘
                                    │ subprocess sync
                                    ▼
                          ┌──────────────────────┐
                          │ bilibili / live / news │  ← 同步子任务（线程池）
                          └──────────────────────┘
```

- **NapCatQQ**：基于 NTQQ 的无头 Bot 框架，提供 OneBot v11 WebSocket 接口
- **bot.py**：接收 QQ 消息，路由到各 handler；通过 MCP 协议调用子进程
- **jmcomic/server.py** + **pixiv/server.py**：MCP 服务器，运行在子进程中，通过 stdio 与 bot 通信

> MCP 服务器在 bot 启动时自动拉起，停止时自动关闭。

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.11+ | 需要 `asyncio` 和类型语法支持 |
| [NapCatQQ](https://napneko.github.io/) | QQ Bot 框架，提供 OneBot v11 接口 |
| FFmpeg | B 站视频压缩 + Pixiv ugoira → GIF 转换 |
| `mcp` Python SDK | MCP 客户端/服务端协议支持 |

## 配置

### ⚠️ 安全警告

> 以下配置中的值均为**示例**，请替换为你自己的真实密钥。
> **切勿将 API Key、Session ID 等敏感信息提交到 Git 仓库。**
> `.env` 文件已在 `.gitignore` 中排除，无需担心误提交。

### 1. 创建 `.env`

在 `qq-bot/` 目录下创建 `.env` 文件：

```ini
# ── Bot 基础配置 ──
BOT_HOST=127.0.0.1
BOT_PORT=8080
BOT_TOKEN=                          # 与 NapCatQQ token 一致（可选）

# ── AI 聊天（必填） ──
OPENAI_API_KEY=sk-your-key-here     # ← 改成你的 API Key（OpenAI / DeepSeek 均可）
OPENAI_BASE_URL=                    # ← 可选，使用 DeepSeek 则填 https://api.deepseek.com
OPENAI_MODEL=                       # ← 可选，默认 gpt-4o-mini，可换成 deepseek-v4-flash 等

# ── Pixiv（二选一，推荐 OAuth） ──
PIXIV_PHPSESSID=your_phpsessid      # ← 改成你的 PHPSESSID（功能受限）
PIXIV_REFRESH_TOKEN=                # ← 改成你的 OAuth Refresh Token（全功能）

# ── B站（可选，提升视频下载成功率） ──
BILIBILI_COOKIES_FILE=              # ← 可选，默认自动查找 qq-bot/bilibili/bilibili_cookies.txt
```

各字段说明：

| 字段 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 你的 API Key，支持 OpenAI、DeepSeek、任意兼容 OpenAI SDK 的提供商 |
| `OPENAI_BASE_URL` | 仅当使用第三方 API 时需要（如 `https://api.deepseek.com`），留空则默认 OpenAI |
| `OPENAI_MODEL` | 模型名，如 `gpt-4o-mini`、`deepseek-v4-flash`；留空默认 `gpt-4o-mini` |
| `PIXIV_PHPSESSID` | 从浏览器 Cookies 中获取的 Pixiv Session ID（登录 pixiv.net 后 F12 → Application → Cookies → `PHPSESSID`） |
| `PIXIV_REFRESH_TOKEN` | 通过 OAuth PKCE 流程获取（见下方"获取 Pixiv Token"），功能更全 |
| `BILIBILI_COOKIES_FILE` | Netscape 格式 cookies 文件路径；留空则自动查找 `bilibili/bilibili_cookies.txt` |

### 2. 安装 NapCatQQ

参考 [NapCatQQ 官方文档](https://napneko.github.io/guide/) 安装并登录 QQ 账号。

配置反向 WebSocket（修改 `onebot11_<QQ号>.json`）：

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

按提示在浏览器中登录 Pixiv 并授权，Token 自动写入 `.env`。OAuth 模式解锁排行榜、用户收藏、趋势标签等全部功能。

### 4. 获取 B站 Cookies（可选）

1. 在浏览器中登录 bilibili.com
2. 用 [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) 扩展导出 Netscape 格式 cookies
3. 保存为 `qq-bot/bilibili/bilibili_cookies.txt`

### 5. 启动机器人

```bash
# 终端 1：启动 Bot
cd qq-bot
python bot.py

# 终端 2：启动 NapCatQQ
cd NapCatQQ目录
napcat.bat
```

Bot 启动时会自动拉起 JMComic 和 Pixiv 的 MCP 子进程。

## 命令列表

### 基础命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/forget` | 清空 AI 对话记忆 |
| `@机器人 <消息>` | 群聊中 @机器人 发起 AI 对话 |
| `<任意消息>` | 私聊中直接 AI 对话 |

AI 对话会自动识别意图并调用工具：
- "帮我搜一下碧蓝档案的图" → Pixiv 搜索
- "今天P站排行榜" → 排行榜
- "帮我下这个漫画 JM123456" → 下载 JM 漫画

### JMComic

| 命令 | 说明 |
|------|------|
| `/jm <ID>` | 下载漫画并转为 PDF |
| `/jm <ID> <输出目录>` | 指定输出目录 |

### Pixiv

| 命令 | 说明 |
|------|------|
| `/pixiv search <关键词>` | 搜索插画 |
| `/pixiv rank [模式]` | 排行榜 |
| `/pixiv detail <ID>` | 作品详情 |
| `/pixiv related <ID>` | 相关作品 |
| `/pixiv recommend` | 个人推荐 |
| `/pixiv trending` | 热门标签 |
| `/pixiv dl <ID>` | 下载作品 |
| `/pixiv user <ID>` | 用户信息 |
| `/pixiv bookmarks <用户ID>` | 用户收藏 |

搜索高级选项：`/pixiv search <词> -t tags|caption|keyword -s date_desc|popular_desc -d day|week|month -o <偏移>`

### Bilibili

| 命令 | 说明 |
|------|------|
| `/bili <链接或BV号>` | 下载视频（自动压缩适配 QQ） |
| `/live` | 查询已关注主播中谁在直播 |
| `/下一页` / `/上一页` | 直播列表翻页 |
| `/第N页` | 跳转到第 N 页 |
| `/break` | 退出直播浏览 |

### 游戏新闻

| 命令 | 说明 |
|------|------|
| `/news` | 新闻菜单 |
| `/国内新闻` | ali213 最新 5 条（带图） |
| `/国外新闻` | 国外新闻源子菜单 |
| `/vgc` | VGC 新闻（带中文翻译） |
| `/resetera` | ResetEra 爆料帖 |
| `/insider` | Insider Gaming |
| `/steam` | Steam 即将发售 |

## 技术细节

### MCP 子进程架构

`bot.py` 通过 `McpManager`（`mcp_client/client.py`）启动两个 MCP stdio 子进程：

1. `python jmcomic/server.py` — JMComic 服务
2. `python pixiv/server.py` — Pixiv 服务

通信采用 MCP stdio 协议（JSON-RPC over stdin/stdout），对上层返回纯文本字符串，`AIHandler` 无需感知底层协议变化。

### Pixiv 认证模式

| 模式 | 配置 | 功能范围 |
|------|------|----------|
| PHPSESSID | `PIXIV_PHPSESSID` | 搜索、详情、相关作品 |
| OAuth | `PIXIV_REFRESH_TOKEN` | 全部功能（排行榜、用户收藏、趋势标签等） |

推荐使用 OAuth 模式。

### AI 人设

塔菲是永雏塔菲（Ace Taffy），17 岁的粉发金瞳少女、天才发明家、王牌侦探。回复风格：软糯、松弛、沙雕、毒舌但内心温柔。通过 OpenAI 兼容 API 驱动，支持 tool calling 自动调用下载/搜索等工具。
