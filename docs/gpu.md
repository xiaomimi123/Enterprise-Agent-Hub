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

## 工作流与对外接口

| 工作流 | 模型 | 用途 | 入口 |
|---|---|---|---|
| `image-gen` | Z-Image-Turbo（int8，8 步） | 文生图，画幅 3:4 / 1:1 / 4:3 / 9:16 / 16:9，一次 1–4 张 | MCP `generate_cover`、`generate_image`；HTTP `POST /api/v1/images` |
| `video-h3` | MiniMax-H3 + Turbo 4 步 LoRA | 文生视频（带声音，24fps），2–10 秒 | MCP `generate_video`；HTTP `POST /api/v1/videos` |
| `video-h3-i2v` | 同上，参考图作首帧 | 图生视频，画幅跟随参考图（约 0.4 百万像素） | MCP `generate_video_from_image`（只收中枢签发的图片链接）；HTTP `POST /api/v1/videos/from-image`（上传 PNG/JPEG/WEBP，≤ 10MB） |

权限与审计统一在 `generation.py`：岗位包需包含 `image.cover` / `image.generate` / `video.generate` 之一，且只开放给官方 agent。MCP 工具最多等 90 秒，没完成就返回任务号，用 `get_task` 查询；HTTP 接口只入队，立即返回 202 和任务号。

```bash
# 提交（令牌是员工的 Casdoor 令牌，与 MCP 相同）
curl -X POST http://<中枢>:8088/api/v1/videos -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"      -d '{"prompt": "一杯热拿铁，蒸汽缓缓升起，镜头缓慢推进", "aspect": "9:16", "seconds": 4}'
# → {"task_id": "gpu-…", "status": "排队中", "ahead": 0, "trace_id": "api-…"}
curl http://<中枢>:8088/api/v1/tasks/gpu-… -H "Authorization: Bearer $TOKEN"   # 完成后含 images / videos 下载链接
```

**图生视频的参考图**：HTTP 上传的图片先校验格式和大小，存到 `outputs/_inputs/`；调度服务派发时用 ComfyUI 的 `POST /upload/image` 传到该节点，再填进工作流的 LoadImage。MCP 工具只接受中枢自己签发、未过期的下载链接（例如刚生成的封面），**不抓取任意网址**，避免被用来探测内网（SSRF）。

**按人限流**：每人最多同时 `HUB_GPU_MAX_PENDING_PER_USER`（默认 3）个未完成任务，超出时 MCP 返回提示、HTTP 返回 429，并记一条拦截审计。「前面排队 N 个」包含正在生成的任务。

旧的 `xhs-cover` 工作流（SDXL）已并入 `image-gen`：`generate_cover` 现在是它的 3:4 × 3 张预设。已有数据库里的岗位包不会自动获得新工具（岗位包只在库为空时写入演示数据），需在控制台的岗位包里勾选 `image.generate`、`video.generate`。

## 中枢与 GPU 同机部署（一台 Windows 电脑）

中枢跑在 Docker Desktop 里，ComfyUI Desktop 跑在宿主机上，容器通过 `host.docker.internal` 访问它：

`HUB_GPU_NODES=gpu-01|本机 GPU|http://host.docker.internal:8188|RTX 5080 16GB`

ComfyUI 本身没有鉴权：同机部署时把 ComfyUI 的监听地址改成 `127.0.0.1`（容器经 `host.docker.internal` 仍能访问，已实测），不要用防火墙阻止规则拦 8188，会把容器的访问一起拦掉。实测（RTX 5080 16GB，ComfyUI Desktop 0.40）：768×1024 两张图约 24 秒；480×832、约 2.3 秒带声音的视频约 25 秒。

## 接入真实 GPU 机器

1. GPU 机器上安装 ComfyUI，把 `HUB_COMFY_CHECKPOINT` 指定的模型放进 `models/checkpoints/`
2. 以局域网模式启动：`python main.py --listen 0.0.0.0 --port 8188`
3. 中枢 `.env` 里登记：`HUB_GPU_NODES=gpu-01|GPU-01 设计部工作站|http://192.168.1.21:8188|RTX 4090 24GB`（多台用逗号分隔），去掉 `COMPOSE_PROFILES=demo` 里的模拟节点（或保留用于对照）
4. `make up`

ComfyUI 本身没有鉴权，GPU 机器的 8188 端口应只对中枢服务器开放（防火墙或交换机 ACL）。

## 已验证 / 未验证

- 已验证（模拟节点）：MCP 出图、两人同时出图时第二个排队、财务岗位被拒、Hermes 一句话出图、审计两步记录、控制台节点状态、签名链接（正常 / 篡改 / 过期 / 路径穿越）
- 已验证（真实 ComfyUI，本机）：两套工作流直接提交并出图 / 出片；调度服务收取结果的逻辑（保留 .mp4 扩展名、审计、下载链接）
- 已验证（Docker Desktop 全链路，同机部署）：员工令牌登录 → `POST /api/v1/images`、`/videos` → PostgreSQL 队列 → 本机 ComfyUI → 签名链接下载（图 `image/png`、视频 `video/mp4`）；无令牌 401、财务岗位 403 且留下拦截审计；视频运行时新提交的图片排队等待；同一追踪 ID 贯穿提交与完成两条审计。图 2 张 19 秒，4 秒 9:16 视频 43 秒
- 已验证（图生视频）：HTTP 上传参考图 38 秒出片、非图片 400；MCP 先出图再用其链接生成视频 41 秒；内网元数据地址被拒；限流第 4 个任务返回 429
- 未验证：员工端 agent（Hermes）经 MCP 调用新工具（本机没有安装 Hermes）；节点执行中途掉线的恢复（当前任务会一直停在「生成中」，需要后续加超时）

## 容错

调度服务每轮检查正在跑的任务，以下情况自动把任务放回队列（保持原排队顺序，最多重试 1 次，第二次仍不行判失败），每次都记审计：

| 情况 | 判定 |
|---|---|
| 节点掉线 | 节点离线且任务已开始超过 30 秒 |
| 派发中断 | 领取任务超过 2 分钟仍没拿到 ComfyUI 任务号（如派发途中调度服务重启） |
| 运行超时 | 图片 10 分钟、视频 30 分钟；先让 ComfyUI 取消该任务（删除排队 / 中断运行），再改派 |

查询结果时的网络抖动不判失败，下一轮再查；ComfyUI 明确报错（工作流本身有问题）直接失败，不重试。
此前卡在「生成中」的任务会让节点再也领不到新任务，这一机制同时解决了这个问题。

## 后续

- 图生视频（需要上传参考图到 ComfyUI）、视频粗剪等更多工作流；按工作流把任务派给装了对应模型的节点
- 控制台增加「任务」页，查看排队和历史
