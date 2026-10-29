# 应用发布目录

管理员在这里放员工可以「对 agent 说一句话就打开」的本机应用。每个应用一个文件夹：

```
apps/
└── xhs-workbench/            ← 文件夹名 = 应用 id（小写字母、数字、. _ -）
    ├── app.json
    └── 0.7.4.zip             ← 文件名 = app.json 里的 version + .zip
```

`app.json`：

```json
{
  "id": "xhs-workbench",
  "name": "小红书运营工作台",
  "version": "0.7.4",
  "description": "选题、文案、封面、排期、评论私信、数据复盘",
  "entry": "xhs-workbench/scripts/workbench.mjs",
  "requires": {"node": ">=18", "agent_cli": "codebuddy", "capabilities": ["browser"]},
  "setup_args": ["setup"],
  "start_args": ["start", "--open"]
}
```

- `entry` 是解压后包内的启动脚本（相对路径，用 `node` 运行）；`setup_args`（可省略）是启动前先跑一遍的初始化参数；`start_args` 是启动参数，要求脚本把网址以一行 `URL: <地址>` 输出，并且重复调用是幂等的（已在运行时直接返回同一个网址）
- 发布 / 更新：替换 zip 并改 `app.json` 的 `version`，**不需要重启中枢**；员工下次启动时自动拿到新版（正在运行的实例不会被重启，只收到升级提示）
- `requires`（可选）声明依赖：`node` 版本；`agent_cli`（目前只有 `codebuddy`）、`capabilities`（目前只有 `browser`）让接入器打开前预检，缺什么说明并询问安装，只让对应功能不可用，不拦打开；写错的 `requires` 会让该应用不出现在列表里。详见 [接入新应用指南](../docs/app-integration-guide.md) 4.2
- `guide.json`（每个应用都应该有，入库）：控制台「应用」页展示的接入说明，字段和写法见 [接入新应用指南](../docs/app-integration-guide.md) 4.2.3，模板在 [docs/app-guide-template.json](../docs/app-guide-template.json)
- 校验用的 SHA-256 由中枢按文件实际内容计算，不用手填
- zip 和 `app.json` 不会入库（见 `.gitignore`），入库的只有本说明和各应用的 `guide.json`
- 在控制台「岗位包」里给需要的岗位勾选「可打开的应用」后，该岗位的员工才能打开
