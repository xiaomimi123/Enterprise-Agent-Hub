# 文档索引

> 先看 [CHANGELOG.md](CHANGELOG.md)：每次重要更新都记在这里，是了解「最近改了什么」的第一站。项目约定、常用命令和已知的坑见仓库根目录的 [CLAUDE.md](../CLAUDE.md)。

## 怎么用

| 文档 | 内容 |
|---|---|
| [console.md](console.md) | 控制台各页面（成员、岗位包、模型、应用、接入方式、审计、用量……）与数据来源 |
| [agent.md](agent.md) | 员工端接入器：登录、一键接入、MCP 桥、CodeBuddy / WorkBuddy / Hermes、在线状态、应用启动 |
| [mcp-server.md](mcp-server.md) | 中枢 MCP Server：工具、权限、审计、知识库、对话模型上游与**模型价格** |
| [app-integration-guide.md](app-integration-guide.md) | **接入新应用指南**：把开源工作台 / 智能体改造成中枢应用的模式、判断标准、契约、改造清单、已知限制 |
| [gpu.md](gpu.md) | 出图出视频：本机 GPU、第三方出图 API、H3 网关三条线，调度容错，通道切换 |
| [billing.md](billing.md) | 计费与额度：岗位包选中枢模型或自带模型、月度额度、GPU 额度 |
| [../agent/README.md](../agent/README.md) | 接入器用法与一键脚本（含 Node.js / CodeBuddy CLI 的安装询问和环境变量） |
| [../hub/README.md](../hub/README.md) | 部署：服务清单、端口、初始化、成员账号管理、登录页资源 |

## 设计与决策

| 文档 | 内容 |
|---|---|
| [decisions/](decisions/) | 架构决策记录（如为什么自研 MCP Server） |
| [superpowers/specs/](superpowers/specs/) | 设计文档：应用分发与「打开工作台」、控制台「模型」页 |
| [superpowers/plans/](superpowers/plans/) | 对应的实施计划（RAGFlow 知识库、应用分发、模型管理） |
| [00-启动计划.md](00-启动计划.md) | 最初的阶段 0 计划（**历史文档**：其中的钉钉登录方案已放弃，身份改为 Casdoor 自建账号） |

## 归档（可能已过时）

- `三年级六班集团-企业智能体中枢-开发与架构文档.docx / .pdf`：47 页开发与架构文档，**截至 2026-10-19**，之后的变化（成员管理、模型价格、CodeBuddy、H3 网关、应用分发后续等）见 [CHANGELOG.md](CHANGELOG.md) 和上面各专题文档。需要时再整体重新生成。

## 维护规则

重要更新必须同步：加一条 `CHANGELOG.md` → 更新受影响的专题文档 → 结构变了就改根 `README.md` 和本索引。
