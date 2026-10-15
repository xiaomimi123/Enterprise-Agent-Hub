# GPU 调度

## 目的

公司里只有少数几台带 N 卡的机器。把它们注册成「能力节点」，全公司共享：运营同事的 agent 说一句「帮我出封面」，中枢把任务排进队列，派给空闲的 GPU 节点执行，结果交回给员工。对应启动计划的第 4 步。

## 链路

```
员工 agent ──generate_cover──> hub-mcp ──写入队列──> gpu_tasks（PostgreSQL）
                                                        │
                       hub-worker（调度服务）<──────────┘
                         ├─ 每 10 秒刷新节点状态（/system_stats）
                         ├─ 给空闲节点派任务（POST /prompt，每个节点同时只跑一个）
                         └─ 收取结果（/history → /view），存到 data/outputs/<任务>/
员工 <── 带签名的下载链接（console-web /api/files/...，7 天有效）
```

## 关键设计

**节点就是标准 ComfyUI，不装插件。** 中枢只用 ComfyUI 自带的 HTTP 接口：`POST /prompt`、`GET /history/{id}`、`GET /view`、`GET /system_stats`。GPU 机器上照常运行 ComfyUI（加 `--listen` 让局域网可访问），在 `.env` 的 `HUB_GPU_NODES` 里登记即可。

**工作流是模板文件。** `gpu-node/workflows/xhs-cover.json` 是 ComfyUI 的 API 格式工作流（3:4 竖版，一次 3 张），其中的 `{{prompt}}`、`{{seed}}`、`{{checkpoint}}` 等在派发时替换。设计师在 ComfyUI 里调好工作流后，用「导出（API）」替换这个文件，把需要变化的值改成占位符即可。只读挂载进容器，改完不用重建镜像。

**队列在数据库里。** 任务状态 `queued → running → done / failed`。领取任务用 `FOR UPDATE SKIP LOCKED`，以后多开几个调度进程也不会重复派发。员工端的 MCP 调用最多等 90 秒：完成就直接返回图片链接；没完成就返回任务号，用 `get_cover_task` 查进度。

**权限与审计。** `generate_cover` 要求岗位包含 `image.cover` 工具，且只开放给官方 agent；外部智能体和没有该工具的岗位（如财务）被拒绝并记审计。派发和完成各记一条审计，与发起它的 MCP 会话共用同一个追踪 ID，控制台里能看到「派发封面任务 → GPU-01 生成 3 张，耗时 4 秒」。

**下载链接带签名。** 链接里带有效期和 HMAC 签名（密钥 `HUB_FILE_SECRET`），员工直接点开即可，不需要登录控制台；篡改、过期、试图跳出输出目录的请求一律 404。

**控制台显示真实状态。** 总览的「GPU 能力节点」卡片读取 `gpu_nodes` / `gpu_tasks`：在线 / 忙碌 / 空闲 / 离线、显存占用、全局排队数、今日完成数。

## 开发用模拟节点

`console/backend/app/mock_comfyui.py`，在 `demo` profile 下作为 `mock-comfyui` 服务运行，接口与真 ComfyUI 一致：一次只处理一个任务，每个约 4 秒，按提示词里的主文案画 3 张占位封面。`make bootstrap-demo` 在没有配置节点时会自动登记它。

```bash
cd console/backend && uv run python scripts/gpu_smoke.py   # 两人同时出图（第二个排队）+ 财务被拒
```

## 接入真实 GPU 机器

1. GPU 机器上安装 ComfyUI，把 `HUB_COMFY_CHECKPOINT` 指定的模型放进 `models/checkpoints/`
2. 以局域网模式启动：`python main.py --listen 0.0.0.0 --port 8188`
3. 中枢 `.env` 里登记：`HUB_GPU_NODES=gpu-01|GPU-01 设计部工作站|http://192.168.1.21:8188|RTX 4090 24GB`（多台用逗号分隔），去掉 `COMPOSE_PROFILES=demo` 里的模拟节点（或保留用于对照）
4. `make up`

ComfyUI 本身没有鉴权，GPU 机器的 8188 端口应只对中枢服务器开放（防火墙或交换机 ACL）。

## 已验证 / 未验证

- 已验证（模拟节点）：MCP 出图、两人同时出图时第二个排队、财务岗位被拒、Hermes 一句话出图、审计两步记录、控制台节点状态、签名链接（正常 / 篡改 / 过期 / 路径穿越）
- 未验证：真实 ComfyUI 与真实工作流（需要 GPU 机器）；节点执行中途掉线的恢复（当前任务会一直停在「生成中」，需要后续加超时）

## 后续

- 运行超时与重试：节点掉线或 ComfyUI 报错时自动改派
- 视频粗剪等更多工作流；按工作流把任务派给装了对应模型的节点
- 控制台增加「任务」页，查看排队和历史
