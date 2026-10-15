"""配置：从环境变量读取，开发时自动加载 console/backend/.env。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# 仓库根目录（开发时用来定位 skills/、vault/）；容器内路径较浅，由环境变量指定目录
_parents = Path(__file__).resolve().parents
ROOT = _parents[3] if len(_parents) > 3 else _parents[-1]


@dataclass(frozen=True)
class Settings:
    # demo：全部演示数据，不需要登录；casdoor：Casdoor 登录 + 成员与组织用 Casdoor 真实数据
    mode: str = os.getenv("HUB_CONSOLE_MODE", "demo")
    cors: str = os.getenv("HUB_CONSOLE_CORS", "http://localhost:5173")
    public_url: str = os.getenv("CONSOLE_PUBLIC_URL", "http://localhost:5173")

    # 服务端访问 Casdoor 的地址（容器内为 http://casdoor:8000）
    casdoor_endpoint: str = os.getenv("CASDOOR_ENDPOINT", "").rstrip("/")
    # 浏览器访问 Casdoor 的地址（登录跳转、退出）；不填则与 CASDOOR_ENDPOINT 相同
    casdoor_public_url: str = (os.getenv("CASDOOR_PUBLIC_URL") or os.getenv("CASDOOR_ENDPOINT", "")).rstrip("/")
    casdoor_org: str = os.getenv("CASDOOR_ORG", "")
    casdoor_app: str = os.getenv("CASDOOR_APP", "")
    casdoor_client_id: str = os.getenv("CASDOOR_CLIENT_ID", "")
    casdoor_client_secret: str = os.getenv("CASDOOR_CLIENT_SECRET", "")

    # 中枢数据库：岗位包、成员分配、审计事件（casdoor 模式必填）
    database_url: str = os.getenv("HUB_DATABASE_URL", "")
    # 技能仓库（SKILL.md）与知识库（Obsidian vault）所在目录
    skills_dir: str = os.getenv("HUB_SKILLS_DIR", str(ROOT / "skills"))
    vault_dir: str = os.getenv("HUB_VAULT_DIR", str(ROOT / "vault"))

    # MCP Server：对外地址，以及哪些 Casdoor 应用的令牌算「官方 agent」、哪些算「外部智能体」
    mcp_public_url: str = os.getenv("HUB_MCP_PUBLIC_URL", "http://localhost:8200/mcp")
    agent_client_ids: tuple[str, ...] = tuple(x for x in os.getenv("HUB_AGENT_CLIENT_IDS", "").split(",") if x)
    external_client_ids: tuple[str, ...] = tuple(x for x in os.getenv("HUB_EXTERNAL_CLIENT_IDS", "").split(",") if x)
    # 员工端登录时由中枢代为换取令牌，agent 应用的密钥只保存在中枢
    agent_client_secret: str = os.getenv("HUB_AGENT_CLIENT_SECRET", "")
    # 开发环境允许员工端用账号密码登录（生产环境走浏览器 / 钉钉扫码）
    agent_password_login: bool = os.getenv("HUB_AGENT_PASSWORD_LOGIN", "false").lower() == "true"

    # 模型网关 New API：服务端访问地址、员工端访问地址、管理员访问令牌，以及下发给员工的默认模型
    newapi_endpoint: str = os.getenv("NEWAPI_ENDPOINT", "").rstrip("/")
    newapi_public_url: str = (os.getenv("NEWAPI_PUBLIC_URL") or os.getenv("NEWAPI_ENDPOINT", "")).rstrip("/")
    newapi_access_token: str = os.getenv("NEWAPI_ACCESS_TOKEN", "")
    newapi_admin_id: str = os.getenv("NEWAPI_ADMIN_ID", "")
    default_model: str = os.getenv("HUB_DEFAULT_MODEL", "")
    # 用量折算人民币的汇率（New API 的额度以美元计）
    usd_cny: float = float(os.getenv("HUB_USD_CNY", "7.2"))

    # 会话 cookie 是否只走 HTTPS；生产环境有 HTTPS 时设为 true
    cookie_secure: bool = os.getenv("HUB_COOKIE_SECURE", "false").lower() == "true"

    @property
    def auth_enabled(self) -> bool:
        return self.mode != "demo"

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/callback"


settings = Settings()
