# 改进建议：让 agent 帮技能和知识库「自我进化」

员工的 agent 在干活时最先发现技能写错了、过时了、缺步骤，或者知识库里某条不准确。这一层让它把发现**提成建议**，由人审核后才生效。

**原则：agent 只能提建议，不能直接改。** 采纳由人决定，采纳后才通过现有的版本流程（[技能库](skills.md)、[知识库](knowledge.md)）产生新版本，可回滚。

## 员工的 agent：MCP 工具

| 工具 | 用途 |
|---|---|
| `propose_improvement(kind, target, summary, rationale, proposed_content, knowledge_base, evidence)` | 提交建议。`kind`：`skill`（改技能，target 填技能 id）、`doc`（改已有文档，target 填文档名 + knowledge_base 填库名）、`new_doc`（新增文档，必须带完整内容）。`proposed_content` 最好带上修改后的完整内容，审核人才能直接看到差异；技能要含开头的 name / description |
| `my_proposals(days)` | 看自己提交过的建议和结果（待处理 / 已采纳 / 已驳回及原因） |

中枢的 MCP 说明里写明了什么时候提：发现错误、过时、缺步骤，或用户反复手动纠正同一处；不是每次任务都提。

## 规则

- **谁能提**：能读到那个技能 / 知识库的员工（按岗位包）；外部智能体不能。
- **限额**：每人每天最多 10 条；同一个人对同一目标同时只能有一条待处理的。
- **谁来审**：本部门内容的建议由该部门主管处理；**全公司内容只有老板和管理员**；老板和管理员可以处理所有的。
- **建议内容是不可信输入**：只给人看（差异对比），从不自动执行或发布；技能建议必须是合规的 SKILL.md，大小有上限。
- **旧版本提醒**：建议提出后目标又被改过，会标记「基于旧版本」，采纳前要勾选「已对照最新内容确认」。

## 审核（控制台「改进建议」页）

- 左边列表按待处理 / 已处理，右边看建议的原因、依据，以及和**当前内容**的差异。
- **采纳并生效**：用建议的内容生成新版本并发布（知识库文档同步到 RAGFlow 检索）。**修改后采纳**：先在编辑框里改，再采纳。没带新内容的建议，审核人在编辑框里写好再采纳。
- **驳回**：必须写原因，会反馈给提出建议的人（`my_proposals`）。
- 采纳后版本的作者是审核人，说明里写「采纳 xxx 的建议：…」；提出人的这次采纳记成一项成果（类型「改进建议」），出现在工作看板里。
- 老板和主管的 `team_report` 日报里带「待处理的改进建议 N 条」。

## 接口（`proposals_api.py`，都经过 `auth.console_user`）

`GET /api/proposals?status=open|closed`、`GET /api/proposals/{id}`、`POST /api/proposals/{id}/accept`（`content` 可选、`note`、`confirm_stale`）、`POST /api/proposals/{id}/reject`（`note` 必填）。数据在 `proposals` 表。

## 验证

`console/backend/scripts/e2e_proposals.py` 是端到端测试：真实 Casdoor 登录（员工走 hub-agent 的 PKCE，主管 / 老板走控制台）、真实 MCP HTTP、真实控制台接口，覆盖提交、限额、权限、采纳、驳回、过期、新增文档同步到 RAGFlow 并被检索到、驳回原因反馈等 38 项；会创建并最后删除测试账号和数据，只还原这次测试改过的版本。在 console-api 容器里运行：

```bash
cd hub && docker compose exec -T console-api python - < ../console/backend/scripts/e2e_proposals.py
```

## 已知限制

- 目前没有「让模型根据多条建议自动起草改写稿」，只有人工审核；以后可以在此基础上加。
- agent 要不要提、提得对不对取决于它自己的判断，中枢只负责收集、审核和反馈。
- 建议只能针对已有的技能、知识库文档和新增文档；新建技能、改知识库属性不在范围内。
