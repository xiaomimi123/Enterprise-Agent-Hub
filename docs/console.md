# 中台控制台设计

## 目的

中枢本身是服务端，没有界面。控制台是管理员和老板看到的「产品门面」，也用来给领导演示方案。它把分散在 Casdoor、New API、RAGFlow 等组件里的管理功能，收拢到一个以「岗位包」为中心的界面中。

## 为什么先做控制台（调整了阶段 0 的顺序）

原计划阶段 0 不做 UI。2026-10-15 决定先做控制台，原因：
- 方便自己看清产品形态，也方便给领导展示功能
- 采用「真实项目 + 演示数据」：代码结构按正式项目写，数据层可替换，之后接真实服务时不用推倒重来

最小链路验证（Casdoor 登录 → MCP 鉴权 → 知识库过滤 → GPU 出图 → 审计）仍然要做，控制台接入真实数据的过程本身就是在验证它。

## 关键设计

**数据源可替换。** 前端只调用后端 `/api/*`。后端只依赖 `providers/base.py` 中定义的 `Provider` 接口，目前由 `DemoProvider` 实现，之后按模块切换：

| 模块 | 演示数据 | 真实来源 |
|---|---|---|
| 组织与成员 | `demo_seed.py` | **已接入**：Casdoor 自建账号（控制台可管理），`providers/casdoor.py` |
| 用量与成本 | `demo_seed.py` | **已接入**：New API 调用日志，按员工专属 key 归属到人和部门 |
| 知识库 | `demo_seed.py` | **已接入**：知识库元数据在 `kbs` 表，文档在 `kb_docs` / `kb_doc_versions`（控制台编辑，`vault/` 只在首次启动时导入），检索走 RAGFlow，见 [knowledge.md](knowledge.md) |
| 技能 | `demo_seed.py` | **已接入**：`skills` / `skill_versions` 表（控制台编辑，`skills/` 只在首次启动时导入），见 [skills.md](skills.md) |
| 部门、主管、老板 | — | **已接入**：部门 = Casdoor 分组，主管 / 老板在 `console_roles`，默认岗位包在 `dept_config`，见 [console-roles.md](console-roles.md) |
| 工作成果 | — | **已接入**：`work_items`（agent / 应用上报）+ 审计与 GPU 任务的自动统计，见 [work-report.md](work-report.md) |
| 改进建议 | — | **已接入**：`proposals`，见 [proposals.md](proposals.md) |
| 岗位包、成员分配 | 内存 | **已接入**：中枢数据库 `role_packs` / `role_assignments` |
| 审计链路 | `demo_seed.py` | **已接入**：中枢 MCP Server 写入的 `audit_events` |
| GPU 节点 | `demo_seed.py` | **已接入**：调度服务维护的 `gpu_nodes` / `gpu_tasks`，见 [gpu.md](gpu.md) |

**演示数据讲故事。** 种子数据围绕方案的卖点设计，而不是随机数：
- 运营员工的一条完整链路：加载技能 → 检索知识 → 写稿 → 合规自查 → GPU 出封面 → 保存草稿
- 越权查询财务资料被拒；提示词注入「忽略限制」同样被拒，用来说明权限在中枢强制执行
- ChatGPT 通过 MCP 接入时，只能读取开放给外部的知识库
- 财务请求强制走本地模型，因此财务部的云端花费为 0
- 时间相对当前时间生成，看板任何时候打开都是最新的；随机种子固定，每次启动内容一致

**岗位包是核心对象。** 岗位包 = 技能 + 知识库 + 工具 + 模型 + 每人月额度 + 本机动作上限 + 外部智能体接入策略。成员通过岗位包获得全部权限，修改岗位包即可批量调整。

## 登录与权限（2026-10-15 接入 Casdoor）

- **OAuth2 授权码流程**：前端发现未登录 → 向后端要 Casdoor 授权地址（state 存在 httpOnly cookie 里防 CSRF）→ Casdoor 登录 → 回到 `/callback` → 后端用 code 换取 access_token
- **会话**：access_token 本身是 Casdoor 签发的 JWT，直接放在 httpOnly cookie `hub_session` 里；每个请求都用 Casdoor 的 JWKS 公钥校验签名、有效期和 audience，后端不存会话状态
- **谁能进控制台**：必须属于配置的企业组织（`CASDOOR_ORG`），并且有三种控制台角色之一：**管理员**（Casdoor 用户的 `isAdmin`）、**老板**、**部门主管**（后两者在「部门与角色」页设置）。其他人看到「无权访问控制台」。老板和主管只能用白名单里的只读接口（外加技能 / 知识库的编辑和审核），主管只看自己负责的部门，见 [console-roles.md](console-roles.md)
- **退出**：清除 cookie，并跳转 Casdoor 的 `/api/logout` 作废令牌、结束 Casdoor 会话，否则会被自动登录回来
- **演示模式不需要登录**，便于离线演示

**成员与组织的映射**：部门 = Casdoor 组织下的分组；成员 = 组织下的用户。成员的岗位包保存在中枢数据库 `role_assignments`，没有记录时按部门的默认岗位包（`policy.DEFAULT_ROLE_PACKS`，按客户实际的部门分组名调整），再没有就用「通用办公」。读取结果缓存 30 秒，修改岗位包后立即刷新。成员的 agent 状态（在线 / 离线 / 未安装）来自接入器的心跳和官方 agent 的工具调用，见 [agent.md](agent.md)「在线状态」。

**岗位包落库**：岗位包定义和成员分配已迁到 PostgreSQL，控制台与 MCP Server 共用，控制台一改，下一次 MCP 调用立即按新岗位包判断。

## 视觉设计

2026-10-15 重新设计，放弃 Ant Design 默认的蓝白后台风格：
- **克制的暖白底**：画布 `#f6f6f3`，白色面板 + 1px 细描边，几乎不用阴影；墨色文字，只用一个靛紫色（`#5b5bd6`）作强调
- **设计令牌集中在 `src/index.css`**，antd 主题在 `main.tsx` 里对齐同一套颜色；通用组件（PageHeader、Panel、Pill、Avatar、Meter、Sparkline 等）在 `src/ui/`
- **部门有固定配色**（`lib.ts` 的 `DEPT_META`），图表、圆点、图标块全站一致
- **总览页讲故事**：问候语里直接写当天的关键数字；「中枢运行拓扑」展示员工 agent / 外部智能体 → 中枢（身份·权限·审计·路由）→ 知识检索 / 模型网关 / GPU / 技能仓库，连线带流动动画
- 数字统一使用等宽数字（tabular-nums），时间戳和文件路径使用等宽字体

## 取舍

- 演示模式数据在内存中，重启即恢复，方便反复演示；不做持久化
- 前端 bundle 未做代码分割，后台系统可以接受，以后需要再按路由拆分

## 下一步

1. ~~控制台登录接 Casdoor~~（已完成）
2. ~~成员与组织接 Casdoor~~（已完成）；身份已决定直接用 Casdoor 自建账号，不接钉钉（成员管理见 [hub/README.md](../hub/README.md)「成员账号管理」）
3. ~~岗位包落库（PostgreSQL）~~（已完成，见 [mcp-server.md](mcp-server.md)）
4. ~~用量接 New API~~（已完成，见 [agent.md](agent.md)）；~~知识库检索换 RAGFlow~~（已完成，见 [mcp-server.md](mcp-server.md)）
5. ~~技能库 / 知识库在控制台编辑、版本、审核；角色与部门；改进建议；工作看板~~（已完成，见 [docs/README.md](README.md) 的专题文档）
