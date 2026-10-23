import os
import tempfile

# 测试固定使用演示模式，不受本地 .env 影响（load_dotenv 不覆盖已有环境变量）
os.environ["HUB_CONSOLE_MODE"] = "demo"

# 接入器的应用根目录（应用健康事件写在它的 logs/ 下）指向临时目录，测试绝不写员工真实的 ~/HubApps
os.environ["HUB_APPS_ROOT"] = tempfile.mkdtemp(prefix="hubapps-test-")
# 接入器的家目录（登录凭证 credentials.json 在这里，路径在加载接入器时就定了）也指向临时目录：
# 曾经因为没隔离，app-doctor 的测试用开发机上真实员工的令牌把测试事件发到了真实中枢
os.environ["HUB_AGENT_HOME"] = tempfile.mkdtemp(prefix="hub-agent-test-")
os.environ["HUB_HEALTH"] = "off"  # 默认不记也不发；测应用健康的用例自己打开
