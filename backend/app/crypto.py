from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        raise SecretError("未配置 ZHIBI_SECRET_KEY，无法加密保存 API Key")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretError("API Key 无法解密：ZHIBI_SECRET_KEY 可能已更换，请重新填写 Key") from exc
