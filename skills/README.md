# 岗位技能仓库

目录结构：`<部门>/<技能 id>/SKILL.md`。文件夹名就是技能 id，岗位包通过技能 id 引用。

技能采用 SKILL.md 格式（markdown + frontmatter：name、description、department、version），可以直接用 Obsidian 打开编辑。
中枢 MCP Server 按员工的岗位包下发技能；控制台「技能库」页面在 casdoor 模式下读取这里的文件。

后续计划拆成独立 git 仓库，供员工端 agent 订阅。
