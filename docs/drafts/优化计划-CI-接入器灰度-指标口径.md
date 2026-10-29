# 优化计划：CI、接入器灰度与回滚、指标口径单一来源（2026-10-29）

来源：项目评审（7.6/10）建议的前三项。目标是把“靠人记得”变成“机器兜底”，并且不改变现有行为（没有配置时和现在完全一样）。

## 1. CI：每次提交自动跑检查

**问题**：后端 350 个测试、前端类型检查和 lint、接入器的 Node 测试全靠人记得跑；提交频率高，迟早漏。

**做法**
- 新增 `.github/workflows/ci.yml`，推送和 PR 都触发，三个并行任务：
  1. 后端：`uv sync` + `pytest -q`（Linux、Python 3.12）。
  2. 前端：`npm ci` + `tsc -b` + `oxlint src`。
  3. 接入器：`python -m py_compile agent/hub_agent.py`，`node agent/tests/*.mjs` 里不依赖 Windows 的部分（preflight / bundle / icon 三个脚本是 PowerShell 相关，放在 Windows runner 上单独一个任务，失败不阻塞前三个的反馈）。
- 另加一个本地入口 `tools/check.sh`（也可 `tools/check.ps1`），把同样的命令跑一遍，提交前用。

**怎么验证**：本机逐条跑工作流里的命令，确认都通过；工作流 YAML 用解析器检查语法。**没法验证的**：GitHub 上真实运行（还没推送、远程是否启用 Actions 未知）。

**不做**：自动部署、覆盖率门槛（先让它跑起来）。

## 2. 接入器灰度与回滚

**问题**：`agent/hub_agent.py` 挂载在中枢上，比员工电脑新就会自动替换，等于“一改就发给所有人”；且版本只增不减，发错了没法让电脑退回去。

**设计**（向后兼容：没有 `agent/rollout.json` 时一切照旧）
- 新增 `agent/rollout.json`（不进 git，只在部署机上；示例 `agent/rollout.example.json`）：
  ```json
  {"stable": "0.5.11", "candidate": "0.5.12", "canary_users": ["zhourunxin"], "force_stable": false}
  ```
- 每个已发布版本存一份快照：`agent/releases/<版本>/hub_agent.py`（不进 git）。工具 `tools/release-agent.py snapshot` 把当前 `hub_agent.py` 存成快照，`set` 修改 rollout.json。
- 中枢侧：
  - 旧版接入器（0.5.8–0.5.11）走原有的 `GET /api/agent/config` 的 `agent_version` 和 `GET /api/agent/hub_agent.py`：有 rollout.json 时，这两个只给 **stable**，所以它们永远拿不到灰度版本，也不会拿到半成品。
  - 新增 `GET /api/agent/update`（带员工令牌可选）：返回这个人该用的版本 `{version, force}`；灰度名单里的人得到 candidate，其他人得到 stable；`force_stable=true` 时返回 `force: true`，允许比本机版本低（回滚）。`GET /api/agent/hub_agent.py?version=` 按版本取快照（只允许 rollout 里列出的版本，防路径穿越）。
- 接入器（0.5.12）：自更新优先问 `/api/agent/update`（失败或 404 退回原逻辑）；`force` 时允许降级；其余校验（合法 Python、版本号一致、含入口、原子替换、备份）保持。
- 控制台“应用健康”里已有各版本人数，不另加页面。

**发布流程（写进文档）**：改代码 → 升 VERSION → `snapshot` → rollout 设 candidate + 灰度名单 → 观察应用健康 → 把 stable 改成新版本 → 出问题把 stable 改回旧版并 `force_stable=true`。

**怎么验证**：单元测试覆盖选版本逻辑（灰度 / 非灰度 / 回滚 / 非法版本 / 无 rollout 文件）；用真实中枢容器接口手工请求；用临时 HOME 里的接入器副本跑一遍自更新、降级。**没法验证的**：真实员工电脑上的自动更新（只用隔离目录模拟）。

**风险**：改 `hub_agent.py` 本身会发布给所有 0.5.8+ 的电脑——因此 **0.5.12 先进快照、先设 stable=0.5.11 + 空灰度名单**，没人自动升级到 0.5.12，等用户确认灰度名单后才放。

## 3. 指标口径：单一来源 + 一致性测试

**问题**：在线 / 活跃 / 花费曾经出现过同一个人在两个页面口径不同（今天的“8 天前”、3 分钟 vs 5 分钟、¥6802）。现状：判断“在线”的代码散在 `presence.member_agent`、`health.merge_presence`，总览的在线人数又是另一处汇总。

**做法**
- `presence.py` 增加唯一的判断函数 `is_online(last_seen, now)`；`member_agent`、`health.merge_presence` 都调用它，不再各自写 `total_seconds() < ...`。
- 加一个“跨页面一致性”测试：同一份在线记录，成员页的状态、应用健康的在线人数、总览汇总（`agents_online`）三者必须一致；再加一条源码检查，禁止 `presence.py` 以外出现直接用在线窗口常量做比较的写法（防止以后又各写各的）。
- 花费口径已经集中在 `NewApi.repriced_quota`，补一条测试：成员用量、按天用量、本月总额用同一份日志算出来的合计相等。

**怎么验证**：新增测试 + 全量后端测试；用真实中枢读成员页和应用健康接口对照（需要管理员登录，已有测试脚本的登录写法）。

## 顺序与提交
1 → 3 → 2（2 最敏感，放最后，且先不放量）。每项独立提交，CHANGELOG 同步，不推送。
