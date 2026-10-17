# GPU 调度

> **当前开发方式（2026-10-17）**：中枢迁往 Windows GPU 工作站，复用已有 ComfyUI；容器使用 `http://host.docker.internal:8188`，不依赖 Tailscale/frp。Windows 侧单机模型测试由交接报告提供，中枢到真机的完整验收尚未完成。步骤和代码边界见 [Windows开发交接.md](Windows开发交接.md)。

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

**工作流是模板文件 + 一张注册表。** 模板放在 `gpu-node/workflows/*.json`（ComfyUI 的 API 格式），`{{prompt}}`、`{{seed}}`、`{{checkpoint}}` 等在派发时替换；设计师在 ComfyUI 里调好后用「导出（API）」覆盖对应文件、把该变的值改成占位符即可，改完不用重建镜像。`app/gpu.py` 的 `WORKFLOWS` 是调度注册表，决定每个工作流用哪个 MCP 工具、等多久：

| 模板 | 用途 | 输出 | 等待 | 要求岗位包的 |
|---|---|---|---|---|
| `xhs-cover.json` | 封面图（SDXL 通用模板） | 3 张 3:4 竖版 | 90 秒 | `image.cover` |
| `zimage-cover.json` | 封面图（Z-Image Turbo，实机在跑） | 1 张 1140×1472 | 90 秒 | `image.cover` |
| `minimax-video-t2v.json` | 短视频 · 文生视频 | 1 条 768×1344、约 4.5 秒含音频 | 15 分钟 | `video.clip` |
| `minimax-video.json` | 短视频 · 图生视频（R2V） | 同上 | 15 分钟 | `video.clip` |

**等待时长写在模板的 `_meta.wait_seconds` 里**，缺省按类型给（图 90 秒、视频 15 分钟）。生图是秒级、视频是分钟级，员工端 agent 一直是同一个「提交 → 等待 → 超时就拿任务号查」的流程。

**队列在数据库里。** 任务状态 `queued → running → done / failed`。领取任务用 `FOR UPDATE SKIP LOCKED`，以后多开几个调度进程也不会重复派发。员工端的 MCP 调用最多等 90 秒：完成就直接返回图片链接；没完成就返回任务号，用 `get_cover_task` 查进度。

**权限与审计。** `generate_cover` 要求岗位包含 `image.cover` 工具，且只开放给官方 agent；外部智能体和没有该工具的岗位（如财务）被拒绝并记审计。派发和完成各记一条审计，与发起它的 MCP 会话共用同一个追踪 ID，控制台里能看到「派发封面任务 → GPU-01 生成 3 张，耗时 4 秒」。

**下载链接带签名。** 链接里带有效期和 HMAC 签名（密钥 `HUB_FILE_SECRET`），员工直接点开即可，不需要登录控制台；篡改、过期、试图跳出输出目录的请求一律 404。

**控制台显示真实状态。** 总览的「GPU 能力节点」卡片读取 `gpu_nodes` / `gpu_tasks`：在线 / 忙碌 / 空闲 / 离线、显存占用、全局排队数、今日完成数。

**视频：图生视频要先把参考图送到节点上。** 参考图在员工电脑上，中枢读不到那个路径，所以 `generate_video` 收的是 **base64**（员工端 agent 读本地图片后编码传过来），中枢解码后上传到节点的 ComfyUI `input` 目录，再按文件名构造 `timeline_data`。帧数由秒数换算到 MiniMax H3 的 `17k+5` 网格（4 秒 → 107 帧 ≈ 4.5 秒），分辨率是 32 的倍数。

**结果可能是视频。** 收取结果时保留节点给出的扩展名（`.png` / `.mp4`），下载接口按扩展名给媒体类型，浏览器能直接播。审计里写「生成 1 条视频」还是「生成 3 张图」按实际结果区分。

## 实机节点（2026-10-16 交接）

用户的 Windows 机器已搭好并接入：

| 项 | 值 |
|---|---|
| 地址 | `http://100.89.237.82:8188`（Tailscale 网段，端口只对 100.64.0.0/10 放行） |
| 硬件 | RTX 5080 16GB / ComfyUI 0.40.0 / PyTorch 2.12.1+cu130，已注册为 Windows 服务开机自启 |
| 生图 | Z-Image Turbo（int8 量化）+ qwen_3_4b 文本编码器 + ae VAE → 约 24 秒/张 |
| 生视频 | MiniMax H3（ref2va / fl2va int8 量化）+ qwen3vl_32b nvfp4 编码器 → 约 8.5 分钟/条（16GB 显存 offload，属正常） |
| 视频硬约束 | 帧数必须 17k+5、分辨率必须 32 的倍数 |

## 开发用模拟节点

`console/backend/app/mock_comfyui.py`，在 `demo` profile 下作为 `mock-comfyui` 服务运行，接口与真 ComfyUI 一致（含 `/upload/image`）：一次只处理一个任务，出图约 4 秒、出视频约 13 秒，按提示词里的主文案画占位图；视频工作流返回一个最小 MP4 容器（只为跑通链路）。`make bootstrap-demo` 在没有配置节点时会自动登记它。

```bash
cd console/backend
uv run python scripts/gpu_smoke.py     # 两人同时出图（第二个排队）+ 财务被拒
uv run python scripts/video_smoke.py   # 文生视频 + 图生视频（base64 参考图）+ 运营岗位被拒
```

## 接入真实 GPU 机器

1. GPU 机器上安装 ComfyUI，把 `HUB_COMFY_CHECKPOINT` 指定的模型放进 `models/checkpoints/`
2. 以局域网模式启动：`python main.py --listen 0.0.0.0 --port 8188`
3. 中枢 `.env` 里登记：`HUB_GPU_NODES=gpu-01|GPU-01 设计部工作站|http://192.168.1.21:8188|RTX 4090 24GB`（多台用逗号分隔），去掉 `COMPOSE_PROFILES=demo` 里的模拟节点（或保留用于对照）
4. `make up`

ComfyUI 本身没有鉴权，GPU 机器的 8188 端口应只对中枢服务器开放（防火墙或交换机 ACL）。

**先决定 ComfyUI 放在哪**：两台机器同网就直接用局域网 IP（不要隧道）；想合并成一台机器、或换成云 GPU 实例，见 [gpu-部署方案.md](gpu-部署方案.md)。以下是不在同一网络时的接入办法。

**Windows 机器与远程节点**：ComfyUI 原生支持 Windows（portable 包即可），中枢只依赖它的 HTTP 接口，操作系统无关。节点不在中枢同网段时，推荐仓库里已配好的 **frp 反向隧道**（`COMPOSE_PROFILES` 加 `frp`，用 `make frpc-config` 生成 Windows 侧配置，中枢填 `http://frps:8189`），步骤见 [frp-隧道接入.md](frp-隧道接入.md)；也可用 WireGuard 等自建组网。8188 绝不直接暴露公网。显存选型见 [部署清单.md](部署清单.md) 第 6 节。

## 已验证 / 未验证

- 已验证（模拟节点）：MCP 出图、两人同时出图时第二个排队、财务岗位被拒、Hermes 一句话出图、审计两步记录、控制台节点状态、签名链接（正常 / 篡改 / 过期 / 路径穿越）
- 未验证：真实 ComfyUI 与真实工作流（需要 GPU 机器）；节点执行中途掉线的恢复（当前任务会一直停在「生成中」，需要后续加超时）

## 后续

- 运行超时与重试：节点掉线或 ComfyUI 报错时自动改派
- 视频粗剪等更多工作流；按工作流把任务派给装了对应模型的节点
- 控制台增加「任务」页，查看排队和历史
