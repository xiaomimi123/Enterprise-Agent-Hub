"""开发用：验证短视频链路——文生视频、图生视频、无权限岗位被拦截、视频结果可下载。

运行（需先 make up；模拟环境用 mock-comfyui，真实环境用交接回来的 GPU 节点）：
    cd console/backend && uv run python scripts/video_smoke.py
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_smoke import session  # noqa: E402


async def main() -> None:
    # 文生视频（不需要参考图）
    await session("liangchenyang", "给新品做一条短视频",
                  [("generate_video", {"prompt": "产品在自然光下缓慢旋转，镜头轻推", "seconds": 4})])

    # 图生视频：参考图按 base64 传入（员工端就是这么传的，中枢读不到员工本机路径）
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 512
    await session("liangchenyang", "让这张产品图动起来", [
        ("generate_video", {"prompt": "镜头缓慢推近，光影流动",
                            "reference_image": base64.b64encode(png).decode(), "seconds": 4})])

    # 运营岗位包没有 video.clip
    await session("linxiaoman", "运营尝试生成视频", [("generate_video", {"prompt": "随便拍点什么"})])


if __name__ == "__main__":
    asyncio.run(main())
