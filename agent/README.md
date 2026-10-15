# 员工端接入器（hub_agent.py）

员工电脑上运行的一个脚本。它**不修改 Hermes 的代码**，只负责把 Hermes 接到企业中枢上：

1. **登录**：打开浏览器登录中枢（生产环境为钉钉扫码），拿到员工本人的令牌
2. **领取配置**：专属模型 key（按人计量）、中枢 MCP 地址、岗位包里的技能
3. **生成独立的 Hermes 配置**：默认在 `~/.hub-agent/hermes`，与员工个人的 Hermes（`~/.hermes`）完全隔开
4. **启动 Hermes**

## 前提

- 已安装 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（`hermes` 命令可用）
- 已安装 [uv](https://docs.astral.sh/uv/)，用来运行脚本（依赖写在脚本头部，自动安装）

## 用法

```bash
# 登录（会打开浏览器）
uv run agent/hub_agent.py login --hub http://<中枢>:8088

# 开发/演示环境可用账号密码登录（中枢需开启 HUB_AGENT_PASSWORD_LOGIN）
uv run agent/hub_agent.py login --hub http://localhost:8088 --username zhouyinuo --password <密码>

# 启动 Hermes（每次启动都会先同步岗位包和技能）
uv run agent/hub_agent.py chat

# 单次提问，后面的参数原样交给 hermes chat
uv run agent/hub_agent.py chat -q "保湿精华有什么卖点？" --oneshot -Q

uv run agent/hub_agent.py status    # 查看登录状态和岗位包
uv run agent/hub_agent.py sync      # 手动重新同步
uv run agent/hub_agent.py logout    # 退出，清除本机的令牌、模型 key 和技能
```

环境变量 `HUB_AGENT_HOME` 可以改数据目录（默认 `~/.hub-agent`），同一台电脑上模拟多个员工时有用。

## 本机会生成的文件

```
~/.hub-agent/
├── credentials.json     # 令牌（权限 600）
├── profile.json         # 最近一次领取的配置摘要
├── skills/<技能>/SKILL.md # 只包含岗位包里的技能，每次同步整体替换
└── hermes/              # 专用的 HERMES_HOME
    ├── config.yaml      # 模型 → New API，MCP → 中枢，技能目录 → 上面的 skills/
    └── .env             # HUB_AGENT_TOKEN、HUB_MODEL_KEY（权限 600）
```

设计说明见 [docs/agent.md](../docs/agent.md)。
