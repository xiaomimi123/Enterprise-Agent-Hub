import os

# 测试固定使用演示模式，不受本地 .env 影响（load_dotenv 不覆盖已有环境变量）
os.environ["HUB_CONSOLE_MODE"] = "demo"
