# 文档索引

> 先看 [CHANGELOG.md](CHANGELOG.md)：每次重要更新都记在这里，是了解「最近改了什么」的第一站。项目约定、常用命令和已知的坑见仓库根目录的 [CLAUDE.md](../CLAUDE.md)。

## 按用途找文档

**部署与运维**

| 文档 | 内容 |
|---|---|
| [../hub/README.md](../hub/README.md) | 部署：服务清单、端口、初始化、成员账号管理、登录页资源、备份 |
| [billing.md](billing.md) | 计费与额度：岗位包选中枢模型或自带模型、月度额度、GPU 额度 |
| [gpu.md](gpu.md) | 出图出视频：本机 GPU、第三方出图 API、H3 网关三条线，调度容错，通道切换 |
| [console.md](console.md) / [../console/README.md](../console/README.md) | 控制台的设计、数据来源、页面、环境变量、本地开发 |

**主管 / 老板（日常管理）**

| 文档 | 内容 |
|---|---|
| [console-roles.md](console-roles.md) | 控制台角色与部门：管理员 / 老板 / 部门主管的权限、默认拒绝、部门配置 |
| [skills.md](skills.md) | 技能库：控制台编辑、版本与回滚、本部门直接生效 / 全公司审核；技能怎么写（只写业务标准） |
| [knowledge.md](knowledge.md) | 知识库：文档查看与编辑、版本与回滚、内容类型 / 负责人 / 复核、同步到检索 |
| [proposals.md](proposals.md) | 改进建议：agent 提建议、主管 / 老板审核采纳 |
| [work-report.md](work-report.md) | 工作成果与进度：员工上报、控制台看板、老板 agent 日报 |

**员工端与接入**

| 文档 | 内容 |
|---|---|
| [agent.md](agent.md) | 员工端接入器的设计：登录、MCP 桥、模型调用归属、在线状态、应用启动与依赖预检、成果上报 |
| [../agent/README.md](../agent/README.md) | 接入器用法与一键脚本（Node.js / CodeBuddy CLI 的安装询问、环境变量、本机文件） |
| [mcp-server.md](mcp-server.md) | 中枢 MCP Server：全部工具、权限、审计、知识库检索、模型上游与价格、数据库表 |

**开发**

| 文档 | 内容 |
|---|---|
| [../CLAUDE.md](../CLAUDE.md) | 项目约定、代码入口、常用命令、已知的坑、发布工作台新版本的步骤、测试要走真实路径 |
| [app-integration-guide.md](app-integration-guide.md) | 接入新应用指南：把开源工作台 / 智能体改造成中枢应用的模式、契约（依赖预检、成果上报）、改造清单、已知限制 |
| [../apps/README.md](../apps/README.md) | 应用发布目录与 `app.json` 格式 |

## 设计与决策

| 文档 | 内容 |
|---|---|
| [decisions/](decisions/) | 架构决策记录（如为什么自研 MCP Server） |
| [superpowers/specs/](superpowers/specs/) | 设计文档：应用分发与「打开工作台」、控制台「模型」页 |
| [superpowers/plans/](superpowers/plans/) | 对应的实施计划（RAGFlow 知识库、应用分发、模型管理） |
| [drafts/](drafts/) | 草稿与记录，如运营技能从工作台手册拆出业务标准的草稿（已发布，仅作记录） |
| [00-启动计划.md](00-启动计划.md) | 最初的阶段 0 计划（**历史文档**：其中的钉钉登录方案已放弃，身份改为 Casdoor 自建账号） |

## 归档（可能已过时）

- `三年级六班集团-企业智能体中枢-开发与架构文档.docx / .pdf`：47 页开发与架构文档，**截至 2026-10-19**，之后的变化（成员管理、模型价格、CodeBuddy、H3 网关、应用分发后续等）见 [CHANGELOG.md](CHANGELOG.md) 和上面各专题文档。需要时再整体重新生成。

## 维护规则

重要更新必须同步：加一条 `CHANGELOG.md` → 更新受影响的专题文档 → 结构变了就改根 `README.md` 和本索引。
