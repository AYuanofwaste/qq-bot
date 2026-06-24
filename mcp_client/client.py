import asyncio
import logging
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("qq-bot.mcp")


class McpManager:
    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._jm_session: ClientSession | None = None
        self._pixiv_session: ClientSession | None = None
        self._bili_session: ClientSession | None = None

    async def start(self):
        base = Path(__file__).resolve().parent.parent

        jm_params = StdioServerParameters(
            command="python",
            args=[str(base / "jmcomic" / "server.py")],
        )
        pv_params = StdioServerParameters(
            command="python",
            args=[str(base / "pixiv" / "server.py")],
        )
        bl_params = StdioServerParameters(
            command="python",
            args=[str(base / "bilibili" / "server.py")],
        )

        jm_read, jm_write = await self._exit_stack.enter_async_context(
            stdio_client(jm_params)
        )
        self._jm_session = await self._exit_stack.enter_async_context(
            ClientSession(jm_read, jm_write)
        )
        await self._jm_session.initialize()
        logger.info("JMComic MCP server connected")

        pv_read, pv_write = await self._exit_stack.enter_async_context(
            stdio_client(pv_params)
        )
        self._pixiv_session = await self._exit_stack.enter_async_context(
            ClientSession(pv_read, pv_write)
        )
        await self._pixiv_session.initialize()
        logger.info("Pixiv MCP server connected")

        bl_read, bl_write = await self._exit_stack.enter_async_context(
            stdio_client(bl_params)
        )
        self._bili_session = await self._exit_stack.enter_async_context(
            ClientSession(bl_read, bl_write)
        )
        await self._bili_session.initialize()
        logger.info("Bilibili MCP server connected")

    async def close(self):
        await self._exit_stack.aclose()

    async def _call_jm(self, tool_name: str, **kwargs) -> str:
        result = await self._jm_session.call_tool(tool_name, kwargs)
        if result.content and len(result.content) > 0:
            return result.content[0].text
        return ""

    async def _call_pixiv(self, tool_name: str, **kwargs) -> str:
        result = await self._pixiv_session.call_tool(tool_name, kwargs)
        if result.content and len(result.content) > 0:
            return result.content[0].text
        return ""

    async def _call_bili(self, tool_name: str, **kwargs) -> str:
        result = await self._bili_session.call_tool(tool_name, kwargs)
        if result.content and len(result.content) > 0:
            return result.content[0].text
        return ""

    async def download_jm_comic(self, jm_id: str, output_dir: str = None) -> str:
        kwargs = {"jm_id": jm_id}
        if output_dir:
            kwargs["output_dir"] = output_dir
        return await self._call_jm("download_jm_comic", **kwargs)

    async def search_illust(
        self,
        word: str,
        search_target: str = "partial_match_for_tags",
        sort: str = "date_desc",
        duration: str | None = None,
        offset: int | None = None,
    ) -> str:
        kwargs = {"word": word, "search_target": search_target, "sort": sort}
        if duration:
            kwargs["duration"] = duration
        if offset is not None:
            kwargs["offset"] = offset
        return await self._call_pixiv("search_illust", **kwargs)

    async def search_user(self, word: str, offset: int | None = None) -> str:
        kwargs = {"word": word}
        if offset is not None:
            kwargs["offset"] = offset
        return await self._call_pixiv("search_user", **kwargs)

    async def trending_tags_illust(self) -> str:
        return await self._call_pixiv("trending_tags_illust")

    async def illust_ranking(
        self,
        mode: str = "day",
        offset: int | None = None,
        date: str | None = None,
    ) -> str:
        kwargs = {"mode": mode}
        if offset is not None:
            kwargs["offset"] = offset
        if date:
            kwargs["date"] = date
        return await self._call_pixiv("illust_ranking", **kwargs)

    async def illust_detail(self, illust_id: int) -> str:
        return await self._call_pixiv("illust_detail", illust_id=illust_id)

    async def illust_related(self, illust_id: int, offset: int | None = None) -> str:
        kwargs = {"illust_id": illust_id}
        if offset is not None:
            kwargs["offset"] = offset
        return await self._call_pixiv("illust_related", **kwargs)

    async def illust_recommended(self, offset: int | None = None) -> str:
        kwargs = {}
        if offset is not None:
            kwargs["offset"] = offset
        return await self._call_pixiv("illust_recommended", **kwargs)

    async def user_bookmarks(
        self,
        user_id: int,
        offset: int | None = None,
        restrict: str = "public",
    ) -> str:
        kwargs = {"user_id": user_id, "restrict": restrict}
        if offset is not None:
            kwargs["offset"] = offset
        return await self._call_pixiv("user_bookmarks", **kwargs)

    async def download(
        self,
        illust_id: int,
        output_dir: str | None = None,
        wait: bool = False,
    ) -> str:
        kwargs = {"illust_id": illust_id, "wait": wait}
        if output_dir:
            kwargs["output_dir"] = output_dir
        return await self._call_pixiv("download", **kwargs)

    async def bili_download_video(self, url: str, output_dir: str = None) -> str:
        kwargs = {"url": url}
        if output_dir:
            kwargs["output_dir"] = output_dir
        return await self._call_bili("download_video", **kwargs)

    async def bili_live_following(self) -> str:
        return await self._call_bili("fetch_live_following")

    async def bili_search_live(self, keyword: str, page: int = 1) -> str:
        return await self._call_bili("search_live", keyword=keyword, page=page)
