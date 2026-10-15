"""开发用：验证 GPU 调度——出封面图、两人同时出图时排队、无权限的岗位被拦截。

运行（需先 make bootstrap-demo 并启动全部服务）：
    cd console/backend && uv run python scripts/gpu_smoke.py
"""

from __future__ import annotations

import asyncio
import time

from mcp_smoke import session


async def timed(user: str, task: str, title: str) -> None:
    start = time.time()
    await session(user, task, [("generate_cover", {"title": title})])
    print(f"  （{user} 用时 {time.time() - start:.1f} 秒）")


async def main() -> None:
    # 两名运营同时出图：节点一次只跑一个，第二个排队
    await asyncio.gather(
        timed("zhouyinuo", "出秋冬保湿精华的封面", "秋冬换季保湿精华"),
        timed("linxiaoman", "出防晒乳新品封面", "通勤防晒不搓泥"),
    )
    # 财务岗位包没有生成封面图的工具
    await session("xujingyi", "财务尝试出封面图", [("generate_cover", {"title": "月度报表"})])


if __name__ == "__main__":
    asyncio.run(main())
