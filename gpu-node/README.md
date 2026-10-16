# GPU 能力节点

GPU 机器上运行标准 ComfyUI，中枢通过它自带的 HTTP 接口派发任务，不需要安装插件。

- `workflows/`：工作流模板（ComfyUI API 格式），`{{占位符}}` 在派发时替换；只读挂载进中枢容器
- 接入步骤、调度设计与模拟节点说明见 [docs/gpu.md](../docs/gpu.md)
- 在 Windows 机器上搭节点（Qwen-Image 生图 + MiniMax-H3 生视频）：照 [windows节点搭建任务书.md](windows节点搭建任务书.md) 执行
