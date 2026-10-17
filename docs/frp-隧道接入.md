# frp 隧道接入 GPU 节点

> **当前不必执行（2026-10-17）**：项目将移到 Windows GPU 工作站同机开发，不启用 frp profile，直接使用 `host.docker.internal:8188`。本篇仅供将来中枢迁云后跨网接入参考，见 [Windows开发交接.md](Windows开发交接.md)。

> 适用场景：中枢服务器与 GPU 机器**不在同一个网络**（例如中枢在云上、GPU 机器放在办公室）。两条机器在同一局域网时不要用这套，直接填局域网 IP 更简单——见 [gpu-部署方案.md](gpu-部署方案.md)。

原理：GPU 机器上的 **frpc** 主动连到中枢上的 **frps**，把它本机的 ComfyUI（8188）映射成中枢内部的 8189 端口。**GPU 机器不需要任何入站端口**，所以家用宽带、公司内网、没有公网 IP 都能用。

```
Windows GPU 机                          中枢服务器（Docker）
  ComfyUI :8188                           公网只开 7000（frpc 连这里）
      ▲                                        │
      └── frpc ──── 主动外连 7000 ────▶ frps ───┴── 内部 8189（不发布到宿主机）
                                                    ▲
                                    hub-worker / hub-mcp 用 http://frps:8189 派任务
```

## 安全设计（为什么这样做）

- ComfyUI **没有鉴权**。因此代理端口 8189 **不发布到宿主机**，只在 compose 网络内可达——公网只能碰到 frps 的控制端口，碰不到 ComfyUI
- 控制端口用 **token + 强制 TLS**；`allowPorts` 把远程端口锁死在 8189，即使 token 泄露，也开不了别的口
- frps 管理页面只绑回环（`127.0.0.1:7500`）

## 中枢侧（一次配置，约 5 分钟）

1. `.env` 里把 frp 加进 profile：

```bash
COMPOSE_PROFILES=demo,frp      # 不用模拟服务时就是 frp
FRP_BIND_PORT=7000             # 唯一要对公网开放的端口
```

2. 令牌已由 `make env` 生成在 `hub/frp/token`（随机、不进 git）。查看：

```bash
make frp-token
```

3. 启动并确认：

```bash
make up
make ps | grep frps            # 应为 running
```

4. **云服务器要在安全组放行 `FRP_BIND_PORT`（7000/TCP）**——这是唯一需要的入站端口。

## GPU 机器侧（Windows，约 5 分钟）

1. 下载 frp：https://github.com/fatedier/frp/releases ，选 `frp_<版本>_windows_amd64.zip`（版本与中枢的 `FRP_VERSION` 一致），解压到 `D:\frp`

2. 生成配置（在中枢服务器上执行，把输出复制到 `D:\frp\frpc.toml`）：

```bash
cd hub && make frpc-config
```

输出长这样（`<中枢公网IP>` 与实际令牌由命令自动填好）：

```toml
serverAddr = "<中枢公网IP>"
serverPort = 7000
auth.method = "token"
auth.token = "<令牌>"
transport.tls.enable = true
transport.heartbeatInterval = 30      # 视频任务要跑 8–9 分钟，心跳留宽一点
transport.heartbeatTimeout = 90

[[proxies]]
name = "comfyui"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8188
remotePort = 8189
```

也可以照 [hub/frp/frpc.toml.example](../hub/frp/frpc.toml.example) 手填。

3. 前台试跑，确认连通：

```
D:\frp\frpc.exe -c D:\frp\frpc.toml
```

出现 `start proxy success` 即成功。中枢侧用 `docker compose logs frps` 能看到 `new proxy [comfyui] type [tcp] success`。

4. 确认在中枢里能摸到 ComfyUI：

```bash
docker compose exec hub-worker python -c "import httpx; print(httpx.get('http://frps:8189/system_stats', timeout=10).status_code)"
```

返回 200 就通了。

5. 注册成 Windows 服务（用 NSSM，开机自启、崩了自动重启）：

```
nssm install frpc D:\frp\frpc.exe
nssm set frpc AppParameters -c D:\frp\frpc.toml
nssm set frpc AppDirectory D:\frp
nssm start frpc
```

6. ComfyUI 保持 `--listen 0.0.0.0 --port 8188`（frpc 从本机 127.0.0.1 连它，不经过防火墙；Windows 防火墙**不需要**为 8188 开任何入站规则）

## 接到中枢（最后一步）

`.env` 里把节点地址指到 frps 的内部端口 —— 注意是 **frps 容器名**，不是 GPU 机器的地址：

```
HUB_GPU_NODES=gpu-01|GPU-01 工作站|http://frps:8189|RTX 5080 16GB
make up
```

控制台「GPU 节点」页显示在线即可。之后员工端一句话出图/出视频，走的就是这条隧道。

## 故障排查

| 现象 | 检查 |
|---|---|
| 控制台里节点一直离线 | `docker compose logs frps` 有没有 `new proxy ... success`；没有就是 frpc 没连上 |
| frpc 报 `login to server failed` | 令牌不一致（中枢 `make frp-token` 对一下）、端口没放行、或 `serverAddr` 写错 |
| frpc 报 `port not allowed` | frps 的 `allowPorts` 只允许 8189，检查 frpc 里的 `remotePort` |
| frpc 报 `i/o timeout` 连不上 | 云服务器安全组/防火墙没放行 7000；或中枢的 `FRP_BIND_PORT` 改了但没同步 |
| 隧道偶尔断、任务失败 | frpc 没注册成服务（前台跑会被关掉）；或机器休眠——电源计划设为「永不睡眠」 |
| 出图正常、出视频中途断 | 视频 8–9 分钟，把 frpc 的 `heartbeatTimeout` 留到 90 以上（已写在模板里） |
| 想确认隧道是否在传数据 | 中枢服务器本机开 `http://127.0.0.1:7500`（frps 管理页） |

## 已验证（2026-10-17，本机）

用 frp v0.71.0 在本机搭了完整链路做验证：

- 两侧配置 `frps verify` / `frpc verify` 语法通过
- frpc 登录成功 → frps 记录 `new proxy [comfyui] type [tcp] success`、`tcp proxy listen port [8189]`
- 经隧道访问映射端口返回与源端口一致的响应（HTTP 200，内容相同）
- **端口限制生效**：frpc 申请 `remotePort = 9999` 时被拒（`start error: port not allowed`），只有 8189 可用

未验证：跨公网（真实云服务器 ↔ 家庭宽带）的实际连通与带宽表现，以及 Windows 上 NSSM 注册服务的步骤——这两项要到真实部署时跑一遍。
