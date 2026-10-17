# GPU 能力节点

> 当前该 Windows 机器也将承担项目开发与中枢容器运行，请先读 [Windows开发交接.md](../docs/Windows开发交接.md)。不要按旧节点搭建任务书重装已有 ComfyUI 或模型。

GPU 机器上运行标准 ComfyUI，中枢通过它自带的 HTTP 接口派发任务，不需要安装插件。

- `workflows/`：工作流模板（ComfyUI API 格式），`{{占位符}}` 在派发时替换；只读挂载进中枢容器
  - `zimage-cover.json` 生图（Z-Image Turbo，实机在跑）· `xhs-cover.json` 生图（SDXL 通用模板）
  - `minimax-video-t2v.json` 文生视频 · `minimax-video.json` 图生视频（R2V）
  - 新工作流：在 ComfyUI 里调好后 **Workflow → Export (API)** 导出，占位符用 `{{prompt}}` 这类写法，
    顶部 `_meta` 里写 `outputs`（输出节点 id）、`kind`（image/video）、`wait_seconds`（中枢等多久）；
    再到 `console/backend/app/gpu.py` 的 `WORKFLOWS` 注册一行（用哪个 MCP 工具、给谁用）
- 接入步骤、调度设计与模拟节点说明见 [docs/gpu.md](../docs/gpu.md)
- 在 Windows 机器上搭节点（Qwen-Image 生图 + MiniMax-H3 生视频）：照 [windows节点搭建任务书.md](windows节点搭建任务书.md) 执行
