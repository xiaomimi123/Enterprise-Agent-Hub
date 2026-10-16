# Windows GPU 节点搭建任务书

> 本文档交给在 **Windows 电脑（RTX 5080 16GB / 64GB 内存）** 上执行的 agent 或运维人员照做。
> 目标：把这台机器变成企业智能体中枢的「GPU 能力节点」——**只装 ComfyUI 和两个开源模型**，中枢通过 ComfyUI 自带的 HTTP 接口派任务，本机不装中枢的任何组件、不需要数据库、不需要任何账号。
>
> 做完后按文末「回报清单」把信息交回中枢侧即可。

## 前提检查

- [ ] `nvidia-smi` 正常，驱动 ≥ 570（50 系需要 CUDA 12.8，随驱动装好）
- [ ] 磁盘剩余 ≥ 150GB（模型文件大，放 SSD），**解压/存放路径用纯英文无空格**（如 `D:\ComfyUI`）
- [ ] 能访问 HuggingFace；访问不动就设镜像：`set HF_ENDPOINT=https://hf-mirror.com`（PowerShell：`$env:HF_ENDPOINT="https://hf-mirror.com"`）

## 任务 1 · 安装 ComfyUI

1. 下载 https://github.com/comfyanonymous/ComfyUI/releases 里最新的 **ComfyUI_windows_portable_nvidia.7z**，解压到 `D:\ComfyUI`
2. 运行 `run_nvidia_gpu.bat`，浏览器打开 `http://127.0.0.1:8188` 能看到界面即成功
3. **验证**：用默认工作流出一张图（50 系必须用最新 portable，旧版 torch 不支持）

## 任务 2 · 安装生图模型（Qwen-Image，主力用途）

ComfyUI 官方重打包版最省事：https://huggingface.co/Comfy-Org/Qwen-Image-ComfyUI （Split Files 页签），按模型卡指引放入：

| 文件 | 放到 ComfyUI 的 |
|---|---|
| `qwen_image_fp8_e4m3fn.safetensors`（扩散模型，约 15–20GB） | `models/diffusion_models/` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors`（文本编码器） | `models/text_encoders/` |
| `qwen_image_vae.safetensors` | `models/vae/` |

16GB 显存跑 fp8 依赖 ComfyUI 自动 offload（64GB 内存足够）；如果 OOM 或想更快，改用社区 GGUF 量化版（https://huggingface.co/city96/Qwen-Image-GGUF ，选 **Q4_K_M / Q5_K_M**，放 `models/unet/`，需要用 ComfyUI-Manager 装一个 **ComfyUI-GGUF** 插件）。

**验证**：加载 ComfyUI 模板库里的 Qwen-Image 模板，生成一张 **1140×1472（3:4 竖版）** 图，画质正常。

## 任务 3 · 安装生视频模型（MiniMax-H3）

1. 模型页：https://huggingface.co/MiniMaxAI/MiniMax-H3 （33B 图生视频，带音频，4–15 秒 @24fps）。模型卡里有 **ComfyUI 官方教程和 R2V（图生视频）/T2V 工作流模板**，照着做
2. 16GB 显存装不下 BF16：在模型页的社区量化列表（约 77 个，搜 MiniMax-H3 的 GGUF/fp8 fork）里选**最小可用的量化档**，能跑起来优先，画质靠 Turbo LoRA 补（https://huggingface.co/MiniMaxAI/MiniMax-H3-Turbo-Lora 附近按教程挂载）
3. 至少装 **Ref2VA（图生视频）**；FL2VA（文生视频）硬盘富余就一起装

**验证**：用模板生成一条 **4 秒、短边 768、竖版**的视频，有画面有声音。注意：16GB 属于 offload 档，一条视频几分钟到十几分钟是正常的，**能出片即通过**，不要追求速度。

## 任务 4 · 常驻运行与安全

- [ ] 开机自启 + 参数：用 NSSM 把 `run_nvidia_gpu.bat` 注册为 Windows 服务（参数加 `--listen 0.0.0.0 --port 8188`），或计划任务登录时启动
- [ ] 电源计划：**永不睡眠**（控制台 → 电源选项，屏幕可关、系统不睡）
- [ ] 防火墙：8188 端口**只对中枢服务器的 IP / 隧道网段放行**；ComfyUI 没有登录功能，**绝不能对公网开放**
- [ ] 远程维护：装 ToDesk 或向日葵；RDP(3389) 不要暴露公网
- [ ] （仅当中枢不在同一网络时）两边都装 Tailscale（https://tailscale.com ）登录同一账号，记下本机分配的 `100.x.x.x` 地址

## 任务 5 · 导出工作流（重要，中枢派任务靠这个）

在 ComfyUI 网页里分别把下面两个工作流**完整跑通一次**，然后菜单 **Workflow → Export (API)** 导出 JSON（注意是「导出 API」，不是普通保存）：

1. **生图**：Qwen-Image，3:4 竖版 1140×1472，单张或 2 张，最后是 SaveImage 节点
2. **生视频**：MiniMax-H3 图生视频（R2V），4 秒、24fps、竖版，最后是保存视频的节点（SaveVideo 等，以实际为准）

导出的 JSON **原样交回**，不要自己改——中枢侧会统一把提示词、尺寸等改成占位符模板。

## 回报清单（全部做完后，把以下内容交回中枢侧）

1. **ComfyUI 访问地址**：`http://<本机局域网IP 或 Tailscale 100.x地址>:8188`，并确认在中枢那台机器上执行 `curl http://<地址>/system_stats` 能返回 JSON
2. **已装模型清单**：文件名、大小、所在目录
3. **两个导出的工作流 JSON**（生图 + 生视频）
4. **耗时参考**：Qwen-Image 一张 1140×1472 要多久；H3 一条 4 秒视频要多久
5. 版本号：ComfyUI 版本、NVIDIA 驱动版本

## 常见问题

| 现象 | 处置 |
|---|---|
| 出图 OOM / 显存不足 | 生图换 GGUF Q4_K_M；视频降量化档；都不行 ComfyUI 启动参数加 `--lowvram` |
| GGUF 模型不识别 | 用 ComfyUI-Manager 安装 ComfyUI-GGUF 插件后重启 |
| HF 下载慢/失败 | `HF_ENDPOINT=https://hf-mirror.com`，或用 huggingface-cli 断点续传 |
| ComfyUI 报 torch/CUDA 错误 | portable 版本太旧，去 releases 拉最新版，不要自己降级 torch |
| 路径含中文/空格报错 | 整个 ComfyUI 移到纯英文路径重来 |

## 红线（不要做的事）

- 不要在本机安装中枢的其他组件（Casdoor / New API / Docker 等），这台机器的角色只有「ComfyUI 节点」
- 不要把 8188 端口映射到公网或内网穿透到公网
- 不要在验证通过前修改任何模型文件名/目录结构（中枢工作流按标准目录引用）
