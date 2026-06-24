import os
import sys
import logging
import tempfile
from pathlib import Path
from mcp.server.fastmcp import FastMCP
import jmcomic


logging.getLogger("jmcomic").handlers = []
logging.getLogger("jmcomic").addHandler(logging.StreamHandler(sys.stderr))

server = FastMCP("jmcomic-downloader")


@server.tool()
def download_jm_comic(jm_id: str, output_dir: str = None) -> str:
    """通过禁漫天堂JM号下载漫画并转换为PDF文件

    Args:
        jm_id: JM漫画ID（例如: 123 或 350234）
        output_dir: PDF文件输出目录（可选，默认为临时目录）
    """
    try:
        if output_dir:
            pdf_dir = Path(output_dir)
            pdf_dir.mkdir(parents=True, exist_ok=True)
        else:
            pdf_dir = Path(tempfile.mkdtemp(prefix="jmcomic_"))

        download_dir = pdf_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        base_dir_posix = download_dir.as_posix()
        pdf_dir_posix = pdf_dir.as_posix()

        option_yaml = f"""
log: true

download:
  cache: true
  image:
    decode: true
    suffix: .jpg

dir_rule:
  base_dir: {base_dir_posix}
  rule: Bd / Aid

plugins:
  after_album:
    - plugin: img2pdf
      kwargs:
        pdf_dir: {pdf_dir_posix}
        filename_rule: 'JM{{Aid}}_{{Aname}}'
"""

        option = jmcomic.create_option_by_str(option_yaml)
    except Exception as e:
        return f"初始化失败: {str(e)}"

    try:
        jmcomic.download_album(jm_id, option)

        def match_jm_id(p: Path) -> bool:
            return p.stem.startswith(f"JM{jm_id}_")

        pdf_files = [p for p in pdf_dir.glob("*.pdf") if match_jm_id(p)]
        if pdf_files:
            pdf_path = str(pdf_files[0])
            import shutil
            if download_dir.exists():
                shutil.rmtree(download_dir)
            return pdf_path
        else:
            return f"下载完成但未找到PDF文件，请检查目录: {pdf_dir}"
    except Exception as e:
        return f"下载失败: {str(e)}"


if __name__ == "__main__":
    server.run(transport="stdio")
