import os
import tempfile

# 测试固定使用演示模式，不受本地 .env 影响（load_dotenv 不覆盖已有环境变量）
os.environ["HUB_CONSOLE_MODE"] = "demo"

# 接入器的应用根目录（应用健康事件写在它的 logs/ 下）指向临时目录，测试绝不写员工真实的 ~/HubApps
os.environ["HUB_APPS_ROOT"] = tempfile.mkdtemp(prefix="hubapps-test-")
