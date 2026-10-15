"""配置：从环境变量读取，开发时自动加载 console/backend/.env。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    # demo：全部演示数据，不需要登录；casdoor：Casdoor 登录 + 成员与组织用 Casdoor 真实数据
    mode: str = os.getenv("HUB_CONSOLE_MODE", "demo")
    cors: str = os.getenv("HUB_CONSOLE_CORS", "http://localhost:5173")
    public_url: str = os.getenv("CONSOLE_PUBLIC_URL", "http://localhost:5173")

    casdoor_endpoint: str = os.getenv("CASDOOR_ENDPOINT", "").rstrip("/")
    casdoor_org: str = os.getenv("CASDOOR_ORG", "")
    casdoor_app: str = os.getenv("CASDOOR_APP", "")
    casdoor_client_id: str = os.getenv("CASDOOR_CLIENT_ID", "")
    casdoor_client_secret: str = os.getenv("CASDOOR_CLIENT_SECRET", "")

    # 会话 cookie 是否只走 HTTPS；生产环境有 HTTPS 时设为 true
    cookie_secure: bool = os.getenv("HUB_COOKIE_SECURE", "false").lower() == "true"

    @property
    def auth_enabled(self) -> bool:
        return self.mode != "demo"

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/callback"


settings = Settings()
