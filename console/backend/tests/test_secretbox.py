"""密钥加密：落库的密钥只能是密文，页面只显示后四位。"""

import dataclasses

import pytest

from app import secretbox


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(secretbox, "settings", dataclasses.replace(secretbox.settings, file_secret="s3cret"))


def test_round_trip_and_ciphertext_hides_plaintext():
    for plain in ("sk-abcdef1234", "密钥-中文-123"):
        token = secretbox.encrypt(plain)
        assert plain not in token and secretbox.decrypt(token) == plain


def test_mask_keeps_last_four_only():
    assert secretbox.mask_secret("sk-abcdef1234") == "••••1234"
    assert secretbox.mask_secret("abc") == "••••"
    assert secretbox.mask_secret("") == ""


def test_wrong_secret_cannot_decrypt(monkeypatch):
    token = secretbox.encrypt("sk-abcdef1234")
    monkeypatch.setattr(secretbox, "settings", dataclasses.replace(secretbox.settings, file_secret="other"))
    with pytest.raises(ValueError):
        secretbox.decrypt(token)


def test_encrypt_without_secret_fails(monkeypatch):
    monkeypatch.setattr(secretbox, "settings", dataclasses.replace(secretbox.settings, file_secret=""))
    with pytest.raises(RuntimeError, match="HUB_FILE_SECRET"):
        secretbox.encrypt("x")
