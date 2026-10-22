# 项目指南（给在这个仓库里开发的人和 AI 助手）

企业智能体中枢：约 50 人企业的私有化多智能体平台。中枢统一管身份、权限、知识、技能、模型、GPU 和审计；员工用自己的 agent（WorkBuddy、CodeBuddy CLI、Hermes 等）通过 MCP 连中枢。总览见 [README.md](README.md)，文档索引见 [docs/README.md](docs/README.md)，**更新记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)**。

## 更新记录规则（必须遵守）

每次有重要更新（新功能、行为变化、配置变化、踩坑结论、版本发布）：
1. 在 `docs/CHANGELOG.md` 最上面加一条（做了什么 / 为什么 / 怎么验证的 / 没验证的是什么）；
2. 同步更新受影响的专题文档（`docs/*.md`、`agent/README.md`、`hub/README.md`）；结构变化时更新根 `README.md`；
3. 和代码放在同一个提交里，或紧接着一个 `docs:` 提交。不要留到「以后再补」。

## 代码入口

| 位置 | 内容 |
|---|---|
| `console/backend/app/` | 控制台后端 + MCP Server + 调度服务，同一镜像 `hub-backend` |
| &nbsp;&nbsp;`main.py` | 控制台 HTTP 接口（`/api/...`，管理员限定）；`mcp_server.py` MCP 工具；`agent_api.py` 员工端接入接口 |
| &nbsp;&nbsp;`policy.py` | 岗位包权限；`db.py` 数据库（审计、岗位包、GPU 任务队列）；`providers/casdoor.py` 成员与组织 |
| &nbsp;&nbsp;`members_admin.py` / `accounts.py` | 成员管理 / 账号状态检查（停用即失效） |
| &nbsp;&nbsp;`roles.py` / `depts_api.py` | 控制台角色（管理员 / 老板 / 部门主管，默认拒绝的接口白名单在 `auth.py`）/ 部门与角色管理，见 [docs/console-roles.md](docs/console-roles.md) |
| &nbsp;&nbsp;`proposals.py` / `proposals_api.py` | agent 提交的改进建议与审核（采纳走 skillstore / kbstore），见 [docs/proposals.md](docs/proposals.md) |
| &nbsp;&nbsp;`kbmeta.py` | 知识库元数据（类型、负责人、复核周期），`content.KB_REGISTRY` 原地刷新 |
| &nbsp;&nbsp;`kbstore.py` / `kb_api.py` | 知识库文档（数据库里带版本，同步到 RAGFlow），见 [docs/knowledge.md](docs/knowledge.md) |
| &nbsp;&nbsp;`skillstore.py` / `skills_api.py` | 技能库（数据库里带版本，主管本部门直接生效、全公司审核），见 [docs/skills.md](docs/skills.md) |
| &nbsp;&nbsp;`work.py` | 工作成果上报与汇总（看板、`team_report`），见 [docs/work-report.md](docs/work-report.md) |
| &nbsp;&nbsp;`newapi.py` / `model_upstreams.py` | 模型网关客户端（员工 key、渠道、模型价格）/ 对话模型上游 |
| &nbsp;&nbsp;`generation.py` / `gpu.py` | 出图出视频统一入口 / 任务队列与调度（本机 ComfyUI、第三方 API、H3 网关三个分支） |
| &nbsp;&nbsp;`imageapi.py` / `h3gateway.py` | 第三方出图 API / H3 生成网关（配置存数据库，密钥加密） |
| `console/frontend/src/pages/` | 控制台页面（React 19 + Ant Design 6）；`api.ts` 接口类型 |
| `agent/` | 员工端接入器 `hub_agent.py`、一键安装脚本 `install.ps1` / `install.sh` |
| `hub/` | `docker-compose.yml`、`Makefile`、`.env` 生成、Casdoor 静态资源 `casdoor-static/` |
| `apps/` | 应用发布目录（zip 和 `app.json` 被 `.gitignore`，只在部署机上） |
| `gpu-node/workflows/` | ComfyUI 工作流模板；`skills/`、`vault/` 岗位技能与知识库 |

## 测试要走真实路径

只调内部函数会漏掉接口层的问题（曾经因此漏掉过被覆盖的方法）。验证功能时要**走真实登录 + 真实接口 / MCP**：参考 `console/backend/scripts/e2e_proposals.py`（里面有控制台和 agent 两种登录的写法）；测试账号和数据用完要删，只还原自己改过的版本，不要动用户真实的编辑。

## 常用命令

```bash
# 后端测试（Windows）
console/backend/.venv/Scripts/python -m pytest -q
# 前端类型检查与 lint
cd console/frontend && npx tsc -b && npx oxlint src
# 重建并重启（改了后端 / 前端 / 安装脚本之后；服务名固定如下）
cd hub && docker compose build console-api console-web && docker compose up -d --force-recreate console-api hub-mcp hub-worker console-web
```

控制台 `http://192.168.0.41:8088`，MCP `:8200`，Casdoor `:8000`，New API `:3000`（`HUB_HOST` 在 `hub/.env`）。当前是本机 Docker Desktop 开发环境；香港云服务器部署计划暂缓，先在本地测试完功能。

## 约定

- 提交信息中文，`feat:` / `fix:` / `docs:` 开头；结尾加 Co-Authored-By 行。**不提交 `.env`、密钥；不替用户推送**（用户明确说「推送」才推）。
- `docs/部署计划-香港云服务器.md` 是用户自己的未跟踪文件，**不要加入提交**。
- 密钥只加密存库（`HUB_FILE_SECRET` 派生），接口和审计里只显示后四位；更换 `HUB_FILE_SECRET` 后已保存的密钥作废。
- 控制台所有写操作写审计（`kind=配置`），详情里不含密码和密钥。

## 已知的坑

- **模型必须设价格**：没设的模型按默认倍率 37.5（每百万 token $75）计费，费用虚高，月度额度几小时被花光，之后网关返回 403。在「模型」页设价格。
- **身份用 Casdoor 自建账号，不接钉钉**。员工首次登录要改初始密码；停用成员 30 秒内令牌失效。
- **Windows**：控制台默认 GBK，脚本要加 `PYTHONUTF8=1`；脚本里写文件别用会把 `\n` 转成真换行的方式；`navigator.clipboard` 在 http 下不可用，复制用 `lib.ts` 的 `copyText`。
- **不要对真实 `%APPDATA%` 跑接入器 `setup`**：它会往 Claude 桌面版配置里加 `enterprise-hub`。测试时用隔离的 `USERPROFILE` / `APPDATA`，或用 `HUB_INSTALL_DRYRUN=1`。
- **CodeBuddy CLI**：`--allowedTools` 逗号拼成一项不生效，要每个工具单独一项；提示词走标准输入；无人值守要放行 `DeferExecuteTool`。
- **员工让 WorkBuddy 等 agent 代跑安装会被沙箱拦**（`iex`、启动进程、计划任务、`reg.exe` 被拒，agent 退出时还会结束它拉起的后台程序）：首选让员工 Win+R 粘贴一行命令自己跑。接入器登录回调必须多线程（浏览器会预连接，单线程会卡死）；安装脚本刷新 PATH 只能合并不能覆盖，npm 用 `npm.cmd`，无 winget 走 Node.js 便携版。
- 登录失败常见原因：登录页放久了或开了多个登录页（状态校验失败）、输错 5 次锁定 15 分钟。

## 接入新应用

要把别的开源工作台 / 智能体改造成中枢的应用，先读 [docs/app-integration-guide.md](docs/app-integration-guide.md)（判断标准、两侧契约、改造清单、已知限制）。下面的小红书运营工作台是样板。

## 小红书运营工作台（独立项目）

源码在 `D:\小红书运自动化运营系统\xhs-workbench1`，**有自己的 git 仓库和 GitHub 远程**（`xhs-workbench1`），不在本仓库里；通过本仓库 `apps/xhs-workbench/` 分发给员工。

用户硬性要求：**自动化只能只读分析（学习博主、分析数据），不能自动发布**。工作台的操作手册（`playbooks/`）与中枢技能是**叠加**关系：中枢技能管业务标准（主管 / 老板在控制台维护），手册管怎么在工作台里做；冲突时格式 / 安全 / 不自动发布以手册为准，见工作台 `docs/hub-integration.md`。CodeBuddy 的浏览器权限默认是只读档，测试档需要用户明确授权，测完切回。

**发布新版本（每次上传都必须升版本号）**：
1. 工作台仓库：改 `xhs-workbench/server/version.mjs` 的 `VERSION`；在 `xhs-workbench/CHANGELOG.md` 顶部加 `## v<版本>` 条目；提交（包由 `git archive` 生成，未提交的不进包）。
2. 跑测试，再 `node tools/package.mjs`。本机没装 ffmpeg，`tests/server.test.mjs` 里有个测试会失败，需先自己跑其余测试，再加 `--skip-tests` 打包。
3. 复制 `dist/xhs-workbench-v<版本>.zip` 到本仓库 `apps/xhs-workbench/<版本>.zip`，把同目录 `app.json` 的 `version` 改成同一个版本（文件名必须等于 version）。不用重启中枢。
4. 在本文件和 `docs/CHANGELOG.md` 记一笔（当前上传到 0.7.9）。

## 开发与架构文档

`docs/三年级六班集团-企业智能体中枢-开发与架构文档.docx / .pdf` 由 `docs/架构文档/*.md` 生成（`cd tools/docs && npm install && node build.mjs`，说明见 [tools/docs/README.md](tools/docs/README.md)）。**不要直接改 docx / pdf，改 Markdown 源文件再生成**；代码片段用 `{{code 路径::函数名}}` 从源码取。系统有重大变化后重新生成一次。

## 相关的外部项目

- H3 生成网关：`D:\minimax h3\genapi`（FastAPI，端口 8100，经 frp 映射到云端），中枢在「模型」页配置地址和 Key。
- 开发过程中的结论和用户偏好另存在 Claude 的记忆目录，不在仓库里。
