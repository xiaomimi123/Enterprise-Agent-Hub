"""密钥加密：第三方 API 的密钥落库前加密，只在调用时解密，页面和日志里只显示后四位。

加密密钥由服务端的 HUB_FILE_SECRET 派生（Fernet）；换了 HUB_FILE_SECRET 后旧密文无法解密，需要重新填写密钥。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    if not settings.file_secret:
        raise RuntimeError("未配置 HUB_FILE_SECRET")
    key = base64.urlsafe_b64encode(hashlib.sha256(b"hub-secretbox:" + settings.file_secret.encode()).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("密钥无法解密（HUB_FILE_SECRET 是否被更换？）") from None


def mask_secret(plain: str) -> str:
    """页面上显示的密钥提示：只留后四位；太短就全部遮住。"""
    if not plain:
        return ""
    return "••••" + (plain[-4:] if len(plain) > 4 else "")
