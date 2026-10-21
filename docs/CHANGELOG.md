# 更新记录

按日期倒序。**每次有重要更新（新功能、行为变化、踩坑结论、配置变化）都要在这里加一条**，写清「做了什么 / 为什么 / 怎么验证的 / 没验证的是什么」。细节看对应文档和提交记录。

> 约定：新条目加在最上面；日期用 `YYYY-MM-DD`；只写对后续开发有用的信息，别写流水账。

## 2026-10-21

**工作台自动上报成果（工作台 0.7.3）**
- 接入器启动应用时设置 `HUB_WORK_OUTBOX`，应用把关键产出追加写到该文件，接入器（桥运行时每 20 秒，或 `hub_agent.py flush-outbox`）按偏移转发到新接口 `POST /api/agent/work-report`；中枢按 人 + 应用 + key 幂等写入 `work_items`（新增 `ext_key`）。工作台上报笔记状态变化（草稿 / 待发布 / 已发布）和对标拆解完成，只写标题和状态。契约见 [work-report.md](work-report.md)。
- 验证：后端测试 276 项通过（新增 outbox 6 项、批量上报 1 项）；工作台新增 5 项通过（全量仅 ffmpeg 用例失败）；真实环境端到端：工作台代码写 outbox → 接入器用真实登录转发 → 库里一行（两次更新合并为「待审核 90%」），再次转发不重复；测试数据已删。**未验证**：桥长期运行时的定时转发、真实工作台界面里的操作触发上报、agent 绕过接口直接改文件的场景（不会上报）。

**工作成果与进度（老板看板）**
- 新增 MCP 工具 `report_work` / `my_work`（员工上报做成了什么）和 `team_report`（管理层，需岗位包开放新工具 `report.view`），新表 `work_items`；控制台新增「工作看板」页（按岗位 / 按个人、成果清单、受阻、无活动的人）。设计、口径和限制见 [work-report.md](work-report.md)。老板的每日日报由老板自己的 agent 定时调用 `team_report` 生成，中枢不推送。
- 验证：后端测试 269 项通过（新增 `test_work.py` 11 项）；`tsc` 通过；重建后用真实库验证上报、更新、他人不能改、汇总；MCP 工具列表含新工具。**未验证**：真实 agent 是否会按说明主动上报、控制台页面在浏览器里的实际渲染（需登录）、老板 agent 的定时日报。

**应用能力预检（工作台 0.7.2）**
- `app.json` 的 `requires` 可声明 `agent_cli` / `capabilities` / `playwright_mcp`，中枢校验（写错则该应用不列出）。接入器打开应用前预检 Node、CodeBuddy CLI、中枢模型、系统浏览器、Playwright，缺什么在返回消息里说明并询问是否安装（`app-doctor <app_id> [--yes]`，只自动执行可自动的项），审计写「缺少能力」。结果写入 `~/.hub-agent/capabilities/<id>.json` 并设 `HUB_CAPABILITIES_FILE`；工作台只拦浏览器功能、不拦打开。
- 验证：中枢后端测试 258 项通过；工作台新增 8 项（含桥层拦截）通过，全量仅 ffmpeg 相关用例因本机缺 ffmpeg 失败（与本次无关）；中枢已能读到 0.7.2 的 `requires`。**未验证**：真实环境里交互式安装提示、`app-doctor` 在真实员工机上的完整流程。
- 代码：`apps.py`、`agent_api.py`、`agent/hub_agent.py`；文档见接入指南 4.2.1。

**文档**
- 新增 [app-integration-guide.md](app-integration-guide.md)《接入新应用指南》：把「应用托管 + 对接契约」模式沉淀成文档（适合接什么、三个接入层级、中枢与应用两侧契约、适配底层 agent 的经验、改造清单、发布流程）。同时记下接第二个应用前要处理的限制：接入器只会用 `node` 启动、`launch_app` 里还有工作台的特例、`HUB_MCP_SERVERS_FILE` 只对 Claude Code 生效、应用自带的模型密钥未统一到中枢。
- 新增 `CLAUDE.md` 项目指南、`docs/README.md` 索引、本更新记录，重写根 `README.md`；清掉各文档里「钉钉」的旧说法。

**成员与登录（身份直接用 Casdoor 自建账号，不接钉钉）**
- 控制台「成员与组织」页支持新建、编辑、重置密码、停用 / 启用、删除、CSV 批量导入。初始密码只在创建 / 重置后显示一次，员工首次登录强制改密（Casdoor 的 `needUpdatePassword`）；密码规则至少 8 位（`casdoor_bootstrap.py` 写入组织）。
- **停用即失效**：停用时 Casdoor 禁止登录 + 回收该员工在模型网关的全部 key；已签发的令牌由 `accounts.is_active` 在 30 秒内拒绝（控制台、MCP、接入器三处都校验，Casdoor 暂时不可用时放行，避免拖垮所有人）。已用真实 Casdoor 验证。代码：`members_admin.py`、`accounts.py`、`members_api.py`。
- Casdoor 登录页不再引用 `cdn.casbin.org`（大陆访问友好）：容器启动时把前端里写死的地址改指向 `/static-cdn`，文件在 `hub/casdoor-static/`。
- 复制按钮在 http 内网访问下失效（`navigator.clipboard` 只在 HTTPS / localhost 可用）→ 统一用 `lib.ts` 的 `copyText`。

**员工接入**
- 接入页改为「发一段话给员工的 agent，由 agent 自己执行安装命令」，员工不用打开命令行；补了新员工入职三步、管理员检查（端口、`HUB_HOST`）和常见问题，全部可一键复制。
- 接入器支持 **CodeBuddy CLI**：把中枢 MCP 写进 `~/.codebuddy/.mcp.json`，把岗位包允许的模型写进 `models.json`（url 要写完整的 `/chat/completions`），放行 `DeferExecuteTool` 以便无人值守调用中枢工具。已在真实 CodeBuddy 2.171.0 上验证：识别 MCP、走中枢模型并按人计量、`whoami` 和出图。
- 一键接入脚本检测 Node.js / CodeBuddy CLI，**缺了先询问再装**（`HUB_INSTALL_TOOLS=yes|no`、`HUB_INSTALL_DRYRUN=1`），没有交互终端时只打印命令。
- **踩坑**：CodeBuddy 的 `--allowedTools` 逗号拼成一项时放行不生效，必须每个工具单独一项；Windows 上 `codebuddy` 是 .cmd 垫片，命令行参数里的多行提示词会被截断，要走标准输入。

**模型价格**
- 控制台「模型」页新增「模型价格」：按美元 / 百万 token 设置每个模型的输入价、输出价，写 New API 的 `ModelRatio` / `CompletionRatio`，立即生效（实测同一请求扣的额度便宜约 500 倍）。
- **根因**：没设价格的模型按 New API 默认倍率 37.5（每百万 $75）计费，费用严重虚高（CodeBuddy 单次请求约 $2），岗位包月度额度几小时被「花光」，之后网关返回 403。上线前必须给所有开放模型设价格。

**小红书运营工作台（独立仓库 `xhs-workbench1`，通过中枢 `apps/` 分发，当前 0.7.3）**
- 适配 CodeBuddy CLI 的 CLI 模式；两档浏览器权限：**只读档**（默认，14 个写类 Playwright 工具全禁用）和**测试档**（放开点击 / 输入，仍禁上传和脚本并屏蔽创作者中心），命令 `browser-mode readonly|test`。用户硬性要求：**自动化只能只读分析，不能自动发布**。
- 在真实环境测通：选题热点（浏览器只读查搜索页）、竞品对标采集 + 拆解、从对标生成选题、一句话让 agent 写 3 篇带封面的草稿。已知：后台采集组件会把登录页的「验证码登录」误判为风控而上锁；agent 采到的数据需先写 `verified` 检查点再写 `observation`，否则服务端拒收。
- **每次重新上传工作台必须升版本号**，步骤见 `CLAUDE.md`「发布小红书工作台」。

## 2026-10-19 ~ 10-20

- **应用分发与 `open_app`**：中枢发布本机应用包（`apps/<id>/app.json` + `<版本>.zip`），岗位包勾选「可打开的应用」，员工对 agent 说「打开 XX」即下载、校验、解压并启动；签名下载链接、MCP 桥拦截 `open_app`。设计见 `docs/superpowers/specs/2026-10-19-app-launcher-design.md`。
- **控制台「模型」页**：对话模型上游（读写 New API 渠道，密钥加密、只显示后四位）；出图通道三选一（本机 GPU / 第三方 apimart API / H3 网关）；视频通道（本机 GPU / H3 网关）。API 出图复用 `gpu_tasks` 队列，worker 增加远程分支，重启后凭已存的第三方任务号恢复轮询，不重复提交。设计与计划见 `docs/superpowers/`。
- **H3 生成网关**接入（本机 `minimax h3` 的 genapi，REST：t2i / t2v / i2v）：中枢自己排队，一次只放少量任务进网关（`HUB_H3_CONCURRENCY`，默认 2）。已验证：出图 12 秒、文生视频 35 秒、图生视频 34 秒。
- 登录页改为「三年级六班集团」品牌左右分栏（`scripts/casdoor_brand.py`）；总览近 14 天趋势改为真实历史；模型调用精确归属到链路（追踪 ID 编进会话专属 key 名）。
- 新增开发与架构文档（Word / PDF，47 页，**截至 10-19，之后的变化以本文件和 `docs/` 下各专题文档为准**）。

## 2026-10-17

- 本机 GPU 出图出视频（ComfyUI 工作流在 `gpu-node/workflows`）、图生视频、GPU 调度容错（节点掉线 / 派发中断 / 超时自动改派）、生成任务页与按人限流。
- 知识库接 RAGFlow（vault 同步、检索失败回退本地）；审计串联：同一追踪 ID 贯通登录、检索、出图与模型调用。
- 接入器：本地 MCP 桥（WorkBuddy 等桌面智能体）、一键接入、技能自动同步到 WorkBuddy、在线状态每分钟报到。
- 计费：岗位包选「中枢模型」或「自带模型」，月度模型额度落到员工 key，GPU 额度在岗位包上。控制台 UI 改版（亮色「作业本」/ 暗色「黑板」双主题）。

## 2026-10-15

- 项目起步：骨架与阶段 0 计划、Docker Compose（Casdoor、New API、RAGFlow）、中台控制台（先演示数据，再接 Casdoor 实时数据）、中枢 MCP Server（令牌鉴权、按岗位包过滤、审计落库）、员工端接入器与专属模型 key、GPU 调度与封面图工具、全部服务容器化。
