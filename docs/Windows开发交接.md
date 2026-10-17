# Windows 开发交接

> 决定日期：2026-10-17。后续在用户的 Windows 工作站上开发本项目；本次只是更新交接文档，没有迁移机器、数据或启动 Windows 服务。正式生产是否上云另行决定。

## 1. 当前方案

硬件：RTX 5080 16GB、Ryzen 9950X3D、64GB DDR5。

- 项目源码与中枢服务搬到这台电脑：Docker Desktop（WSL2 后端、Linux containers）运行 `hub/docker-compose.yml`。
- **复用 Windows 上已经跑通的 ComfyUI、模型和自定义节点**，不要重新安装、升级或覆盖它们。
- Windows 原生 ComfyUI 与中枢容器通过 `http://host.docker.internal:8188` 通信。
- **本机开发不依赖 Tailscale，也不启用 frp profile。** frp 配置保留，未来中枢上云、GPU 留在 Windows 时再用；不要擅自卸载已有网络工具或服务。
- 对话模型仍由 New API 管理；Z-Image Turbo 生图、MiniMax H3 视频由 ComfyUI 执行，两者不是同一套计费链路。

## 2. 接手前先检查，不要覆盖既有环境

- [ ] 查看仓库当前分支、提交与未提交修改；先读本文件、根 README、`docs/gpu.md` 和 `hub/README.md`。
- [ ] 确认 Windows 现有 ComfyUI 的安装目录、服务名、启动参数、模型与自定义节点版本，保留现状。
- [ ] PowerShell 中访问 `http://127.0.0.1:8188/system_stats`，确认本机服务正常。
- [ ] 安装或确认 Docker Desktop 的 WSL2 后端、Linux containers、Ubuntu WSL 集成可用。
- [ ] 在 WSL Ubuntu 内执行项目的 Bash/Makefile 命令；不要直接把这些命令粘到 PowerShell。

建议源码放在 WSL 的 Linux 文件系统，例如 `~/projects/enterprise-agent-hub`，由 Windows 编辑器通过 WSL 打开。ComfyUI 与模型继续留在原 Windows 目录。不要复制 Mac 的 `.venv`、`node_modules`、`dist` 或容器文件层到 Windows。

WSL 初始工具（已有则跳过）：

```bash
sudo apt-get update
sudo apt-get install -y git make openssl
# Docker CLI 由 Docker Desktop 的 WSL integration 提供，不另装第二个 Docker daemon
bash --version
make --version
docker version
docker compose version
```

先不启动 RAGFlow，给 ComfyUI 的 CPU offload 留足系统内存。Docker/WSL 内存限额按实测调整，不能把 64GB 全分给 Docker。

## 3. 数据迁移策略

**默认新建独立开发环境**，不要求继承 Mac 的测试账号、审计和用量。源码通过 Git 或完整源码包交接；未提交文件需另外带过去，`git clone` 不会包含它们。

- 新环境：用 `make env` 生成新凭证，再运行开发初始化。
- 需保留旧数据时：先在旧机做 PostgreSQL 的一致性逻辑备份，分别处理 `casdoor`、`newapi`、`hub` 三个库；同时备份 `.env`、Redis 持久化数据及 `hub/data/outputs/` 等业务文件。恢复后再核对应用凭证、签名密钥和访问地址。
- **不要直接跨系统拷贝正在运行的 `hub/data/postgres/` 目录。** 旧库密码与新 `.env` 不一致时也不能混用。
- 密钥经私密通道传递，不写到交接报告、Git 或聊天输出里。不要修改旧 Mac 的个人 Hermes 环境。

## 4. 启动独立开发环境

以下命令都在 **WSL Ubuntu** 中执行，工作目录为仓库根目录：

```bash
cd hub
make env
# 用编辑器修改 hub/.env，见下面的配置
```

仅在这台 Windows 电脑上使用时：

```dotenv
HUB_HOST=localhost
CASDOOR_ORIGIN=http://localhost:8000
COMPOSE_PROFILES=demo
HUB_GPU_NODES=gpu-01|Windows RTX5080|http://host.docker.internal:8188|RTX 5080 16GB
RAGFLOW_ENDPOINT=
RAGFLOW_API_KEY=
```

注意：
- `HUB_HOST` 是浏览器/员工端访问中枢的地址；`host.docker.internal` 是容器访问 Windows 宿主机的地址，不能互换。容器内的 `localhost` 是容器自身。
- 如需其他员工电脑接入，把 `HUB_HOST` 和 `CASDOOR_ORIGIN` 改成 Windows 稳定局域网 IP，并核对初始化后的 OAuth 回调配置。仅本机联调先用 localhost。
- **初始化前填好 `HUB_GPU_NODES`**，避免 `bootstrap-demo` 在空配置时自动登记模拟 GPU。
- `demo` profile 会启动模拟模型与模拟 ComfyUI；保留它便于开发，但真实任务应只派到上面登记的 Windows 节点。用真实服务测试不等于可以删除模拟测试支持。
- 不要从旧 Mac 复制 Docker 的代理地址。若镜像拉取失败，检查 Windows Docker Desktop 实际代理与镜像源。

```bash
make up
make bootstrap-demo
# bootstrap-demo 会写回 .env 并重建相关容器；确认节点地址仍为 host.docker.internal
make ps
```

`make env` 对已有 `.env` 会直接退出，不会自动补齐新增配置项；接手已有环境时对照 `.env.example` 手动合并，禁止覆盖已有凭证。

访问入口：控制台 `http://localhost:8088`、Casdoor `http://localhost:8000`、MCP `http://localhost:8200/mcp`。New API 仅本机回环访问，端口看 `NEWAPI_PORT`（模板默认 3000；旧 Mac 用过 3001，不能照抄）。

## 5. 必须从容器验证 ComfyUI

```bash
# Windows 本机浏览器能打开 ComfyUI，不代表容器一定能连上
cd hub
docker compose exec hub-worker python -c "import httpx; r=httpx.get('http://host.docker.internal:8188/system_stats',timeout=10); r.raise_for_status(); print(r.json())"
docker compose logs --tail=80 hub-worker
```

若不通：检查 ComfyUI 监听地址、Docker Desktop DNS/WSL 集成和 Windows 防火墙。原先只允许 Tailscale 网段的规则可能不允许 Docker/WSL 流量；只给所需的本机虚拟网络放行，不要把 8188 暴露公网，也不要为了联调关闭整个防火墙。

## 6. 真实联调与验收（下一位 agent 的首要任务）

**先区分证据**：Windows 侧交接报告称已手动跑通生图和视频；此前中枢侧验证的是模拟节点，没有完成中枢 → Windows 真机的整条链路。旧文档中“实机已接入/均验证”的表述不能作为验收记录。

1. 核对 `gpu-node/workflows/zimage-cover.json` 引用的模型和节点类型，先用中枢生成一张真图，确认可下载并打开。
2. 视频先用默认 4 秒参数：核对 `minimax-video-t2v.json`、`minimax-video.json` 与当前 `MiniMaxH3Director`，真实生成一条可播放的视频，并确认音轨。
3. R2V 必须用**有效图片**，通过 base64 传入；不要上传服务器路径或凭证文件。核对上传结果与实际执行节点一致。
4. 验证 `get_cover_task`、结果文件 MIME、签名下载、岗位权限拒绝和审计。接口返回 200 不代表视频可播放。
5. 记录实际模型文件名、节点版本、耗时和峰值内存；交接报告的 24 秒/图、8.5 分钟/视频仅供参考。

接手时需优先核查的代码边界：
- 视频模板的 `total_frames` 仍固定为 107，而 `seconds` 会改变 timeline；非默认时长尚不能直接当作已验证功能。
- MCP 提交目前同步等待最长 900 秒；实测员工端客户端是否会先超时，必要时改为尽快返回任务号、随后轮询。
- `_reference_bytes` 仍允许读取中枢本地路径，应移除该回退，限定有效图片与大小；不能让远端员工读取中枢文件。
- 模拟视频只是占位字节，**不可作为可播放视频验收**。`scripts/video_smoke.py` 当前使用伪图片作为参考图，不能不改就对真实节点运行。

## 7. 日常开发与交接回报

- 中枢相关服务继续通过 Docker 跑；改代码后重建对应镜像，不用 `docker cp` 临时覆盖容器作为长期部署方案。
- 测试环境依赖在 Windows/WSL 重新安装：后端 `cd console/backend && uv sync && uv run pytest`；前端 `cd console/frontend && npm ci && npm run build`（先装 uv 和项目所需 Node）。
- 数据保留在本机持久化目录；不要使用 `docker compose down -v` 或清空 `hub/data/` 解决普通启动问题。
- 本机开发时不需要配置 frps/frpc、不需要公网端口；未来中枢迁云后再读 `docs/frp-隧道接入.md`。

回报只需：源码路径/提交、容器状态、宿主机与容器两侧连通结果、真图/真视频任务 ID、脱敏错误与未完成项。不要回报密码、token、完整 `.env`。确认运行成功后才更新文档为“Windows 端已验证”。
