# 知识库：文档编辑、版本、审核

知识库里的文档（Markdown）存在**数据库**里，带版本，在控制台「知识库」页直接查看和编辑，发布后**自动同步到 RAGFlow 检索索引**。`vault/` 目录只在首次启动时导入为第 1 版（已有的不覆盖），之后以数据库为准，改磁盘上的文件不再生效。知识库本身（名称、部门、密级、是否开放外部、**内容类型、负责人、复核周期**）存在 `kbs` 表里，首次启动从 `demo_seed.KNOWLEDGE_BASES` 导入；`content.KB_REGISTRY` 是原地更新的同一个字典，每个进程最多每 30 秒读一次库（走接口修改会立刻刷新）。

## 谁能怎么改

规则同[技能库](skills.md)，新建、修改、删除、回滚都一样：

| 角色 | 本部门知识库 | 全公司知识库 | 其他部门知识库 |
|---|---|---|---|
| 部门主管 | 保存即生效 | 提交审核 | 不能改（也看不到） |
| 老板 / 管理员 | 保存即生效 | 保存即生效 | 保存即生效 |

审核只有老板和管理员能做（驳回要写原因）；一篇文档同时只有一份待审核的修改。

## 版本与删除

- 每次保存都是新版本；**回滚是用旧内容生成新版本**；保存时带基于的版本号，被别人先改了就拒绝（409）。
- **删除也是一个版本**：文档从检索里去掉，但历史保留，在知识库抽屉底部「已删除的文档」里点开，到「历史版本」选一个版本「找回」。
- 文档名 1–60 个字，不能含 `\ / : * ? " < > |`，不能以点开头；内容 Markdown，不超过 256KB。

## 检索同步

- 发布（保存即生效 / 审核通过 / 删除 / 回滚）后立即把这篇文档同步到 RAGFlow（删旧、传新、触发解析），员工的 agent 马上查到新内容。检索本身读「当前生效的版本」，没有配置 RAGFlow 时回退本地关键词检索，同样读数据库。
- 同步失败不影响文档已保存：列表里状态显示「待同步」，点「重试同步」。
- 全量对齐：`make kb-sync`（`scripts/ragflow_sync.py`）配置了数据库时以数据库里的文档为准。

## 接口（`kb_api.py`，都经过 `auth.console_user`）

| 接口 | 说明 |
|---|---|
| `GET /api/knowledge-bases/{kb}/documents` | 文档列表（版本、片段数、索引状态、待审核数） |
| `GET /api/knowledge-bases/{kb}/documents/{name}` | 内容、版本历史、当前这个人能怎么改 |
| `POST /api/knowledge-bases/{kb}/documents` | 新建 |
| `PUT /api/knowledge-bases/{kb}/documents/{name}` | 保存（`content`、`note`、`base_version`） |
| `DELETE /api/knowledge-bases/{kb}/documents/{name}` | 删除 |
| `POST .../{name}/rollback` | 回滚 / 找回 |
| `GET /api/knowledge-bases/{kb}/deleted` | 已删除的文档 |
| `POST /api/knowledge-bases/{kb}/sync` | 重试同步 |
| `GET /api/kb-reviews`、`POST /api/kb-reviews/{kb}/{name}/{version}` | 待审核列表 / 通过或驳回 |

每次修改写审计（`kb.create` / `kb.edit` / `kb.delete` / `kb.rollback` / `kb.review`），只记知识库、文档名、版本和说明，不记内容。

## 知识库的分类、负责人、复核

- **内容类型**：制度、产品、品牌、案例素材、话术、合规、复盘、其他；列表可按 部门 × 内容类型 × 密级 筛选。
- **谁能改**：只有管理员和老板能**新建**知识库、改名称 / 部门 / **密级 / 是否开放外部**（这两项决定信息会不会外泄；机密库不能开放外部）。部门主管只能改本部门知识库的负责人、内容类型、复核周期和说明。新建后要由管理员在「岗位包」里授权，员工的 agent 才能检索。
- **复核**：每个库有负责人和复核周期（默认 90 天，0 = 不需要），管理员、老板、本部门主管和负责人可以点「标记已复核」重新计时。逾期的在列表里标红；老板和主管的 `team_report` 日报里带上逾期清单（主管只看自己部门和全公司的）。
- 接口：`POST /api/knowledge-bases`（新建）、`PATCH /api/knowledge-bases/{id}`（属性）、`POST /api/knowledge-bases/{id}/reviewed`（标记已复核）。

## 已知限制

- 只支持 Markdown 文档；PDF / Word / Excel 的上传还没做。
- 知识库目前不能删除（只能改属性）；逾期提醒只在控制台和日报里，不单独推送。
- 数据库是唯一真相：想用 Obsidian / git 维护的流程不再适用；**备份要备份数据库**（`skills`、`skill_versions`、`kb_docs`、`kb_doc_versions` 表）。
- 检索结果的 `section`（章节）仍为空（RAGFlow 按分块返回）。
