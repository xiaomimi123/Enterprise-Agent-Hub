# 10 GPU 生成与调度

员工的图片、视频需求被统一转换为「任务」，写入 PostgreSQL 队列，由 hub-worker 派发到执行通道。生成结果存放在中枢，通过带签名的链接交付。2.0 版有三条通道：**本机 GPU（ComfyUI）**、**第三方出图 API**、**H3 生成网关**，控制台「模型」页可手动切换，员工侧工具不变。

## 10.1 统一入口：generation 模块

MCP 工具和 HTTP 接口都调用 `generation.py`，共享同一套权限、限流、额度和审计逻辑。入队前依次检查：工具权限 → 参数合法性 → 每人未完成任务数 → 本月 GPU 额度。

{{code console/backend/app/generation.py::_submit | console/backend/app/generation.py — 入队前的限流与额度检查}}

## 10.2 任务状态机

| 状态 | 含义 | 进入条件 | 离开条件 |
|---|---|---|---|
| queued | 排队中 | 提交；或容错改派放回 | 被空闲节点 / 通道领取 → running |
| running | 生成中 | `claim_task_for` 等领取 | 收到结果 → done；执行报错 → failed；掉线 / 超时 → queued 或 failed |
| done | 已完成 | 结果下载并保存 | 终态 |
| failed | 失败 | 派发异常、执行报错、重试后仍超时 | 终态 |

## 10.3 并发领取：FOR UPDATE SKIP LOCKED

本机 GPU 通道的领取用一条原子 SQL 完成：子查询按提交时间锁定最早的一行排队任务，`SKIP LOCKED` 让并发的调度进程跳过已被锁住的行而不是等待，从而**多个调度进程同时运行也不会重复派发**，且不会互相阻塞。外层先检查该节点是否已有运行中任务，实现「一节点一任务」。

{{code console/backend/app/db.py::claim_task_for | console/backend/app/db.py}}

排队位置向员工展示时，需要计入正在占用节点的任务，否则单节点忙碌时会显示「前面 0 个」：

{{code console/backend/app/db.py::queue_position | console/backend/app/db.py}}

## 10.4 三条通道

| | 本机 GPU | 第三方出图 API（首个对接 apimart） | H3 生成网关 |
|---|---|---|---|
| 任务的 workflow | `image-gen`、`video-h3`、`video-h3-i2v` | `api-image` | `h3-image`、`h3-video` 等 |
| 谁来执行 | GPU 节点上的 ComfyUI | worker 的 API 分支：提交 → 存第三方任务号 → 轮询 → 下载 | worker 的 H3 分支：提交 → 轮询 → 下载 |
| 并发 | 每节点一次一个 | `HUB_IMAGE_API_CONCURRENCY`（默认 4） | `HUB_H3_CONCURRENCY`（默认 2，网关单卡串行） |
| 计入 GPU 用时 | 是 | 否 | 是（计入提交员工的本月 GPU 用时） |
| 视频 | 支持 | 不支持 | 支持（文生 / 图生视频） |

- **切换只影响之后提交的任务**；已排队 / 运行的任务按提交时的通道完成。通道指向的服务不可用（出图 API 被删光、网关被停用）时自动退回本机 GPU。
- 员工拿到的始终是**中枢签发的下载链接**，结果已落在本地，不依赖第三方链接的有效期。
- worker 重启后，已存第三方任务号的任务继续轮询，不会重复提交；失败、超时或返回空图的任务变为 `failed` 并写审计。
- 出图 API 和网关的密钥用 `HUB_FILE_SECRET` 派生的密钥加密后存在 `hub_settings` 表，页面、接口、日志、审计里只出现后四位；**更换 `HUB_FILE_SECRET` 后已保存的密钥无法解密，需要在页面重新填写**。

## 10.5 工作流模板与类型保持

ComfyUI 工作流以 API 格式的 JSON 模板存放在 `gpu-node/workflows/`，其中 `{{占位符}}` 在派发时替换。替换器区分两种情况：**整个值就是占位符**时保留原类型（种子、宽高、帧数是整数，ComfyUI 会校验类型）；占位符嵌在字符串中时做文本替换。

{{code console/backend/app/comfyui.py::load_workflow | console/backend/app/comfyui.py}}

| 模板 | 模型 | 关键参数 |
|---|---|---|
| image-gen | Z-Image-Turbo int8，8 步 res_multistep，CFG 1 | 画幅 3:4 / 1:1 / 4:3 / 9:16 / 16:9（约 0.8 MP，32 的倍数）；1–4 张 |
| video-h3 | MiniMax-H3 fl2va int8 + Turbo 4 步 LoRA | 画幅约 0.4 MP；帧数 17k+5；24fps；带音频 |
| video-h3-i2v | 同上，参考图作首帧 | 参考图缩放到约 0.4 MP 且对齐 32，画幅跟随参考图 |

### 视频帧数的对齐

MiniMax-H3 的时间压缩要求帧数满足 17k + 5。给定秒数 s，先按 24fps 取整，再向上对齐到最近的合法值：n₀ = max(5, round(24·s))，n = n₀ + ((5 − n₀ mod 17) mod 17)。例如 4 秒 → 96 → 107 帧（4.46 秒），5 秒 → 120 → 124 帧，与 MiniMax 官方模板一致。

{{code console/backend/app/generation.py::video_frames | console/backend/app/generation.py}}

## 10.6 容错：节点掉线、派发中断、超时

调度循环每轮执行「刷新节点（10 秒一次）→ 收取结果 → 容错检查 → 派发」。容错检查针对所有运行中任务，按优先级判定几类异常，并把任务放回队列（保持原排队顺序）或判失败：

| 情况 | 判定条件 | 处理 |
|---|---|---|
| 派发中断 | 已领取超过 2 分钟仍无 ComfyUI 任务号 | 改派 |
| 节点掉线 | 节点离线且任务已开始超过 30 秒（给节点状态刷新留余量） | 改派 |
| 运行超时 | 图片 10 分钟、视频 30 分钟 | 先调用 ComfyUI 取消（删除排队 / 中断运行），再改派 |
| 网络抖动 | 查询结果时 httpx 网络错误 | 本轮跳过，下一轮再查，不判失败 |
| 执行报错 | ComfyUI 返回 error 或无输出 | 直接失败（确定性错误，重试无意义） |

每个任务最多重试 1 次（`attempts` 字段），第二次仍异常则判失败。该机制同时消除了一个隐患：卡在 running 的任务会让节点永远领不到新任务。

{{code console/backend/app/gpu.py::_recover max=32 | console/backend/app/gpu.py}}

放回队列只作用于仍在 running 的任务，避免与收取结果竞争：

{{code console/backend/app/db.py::requeue_gpu_task | console/backend/app/db.py}}

## 10.7 结果交付：HMAC 签名链接

生成结果保存在 `outputs/<任务>/`，通过 `/api/files/<任务>/<文件>?exp=…&sig=…` 交付。签名 = HMAC-SHA256(密钥, "路径:过期时间") 的前 32 位十六进制，有效期 7 天。校验使用常数时间比较防计时攻击，并检查解析后的绝对路径必须位于输出目录内，防止 `../` 路径穿越：

{{code console/backend/app/gpu.py::_sign | console/backend/app/gpu.py}}

## 10.8 图生视频的参考图与 SSRF 防护

HTTP 接口接收上传图片：先限制 10MB，再用 Pillow 校验格式（PNG / JPEG / WEBP），存入 `outputs/_inputs/`；调度时通过 ComfyUI 的 `/upload/image` 传到对应节点，再填入工作流的 LoadImage。MCP 工具则只接受**中枢自己签发、未过期的下载链接**——中枢从不去抓取任意 URL，从而杜绝被用来探测内网（如云元数据地址 169.254.169.254）：

{{code console/backend/app/generation.py::image_from_hub_url | console/backend/app/generation.py}}
