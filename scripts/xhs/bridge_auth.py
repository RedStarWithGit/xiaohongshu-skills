"""Bridge WebSocket 鉴权 secret 管理。

secret 文件位于 ~/.xhs/bridge_secret（UTF-8 hex 文本，末尾无换行）。
CLI 与 bridge server 共用同一份 secret，浏览器扩展在 popup 中粘贴完成配对。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

SECRET_FILE = Path.home() / ".xhs" / "bridge_secret"

AUTH_ERROR_MESSAGE = "bridge 认证失败，请检查 ~/.xhs/bridge_secret 与扩展 popup 配置是否一致"


def get_bridge_secret(secret_path: Path | None = None) -> str:
    """读取 bridge 鉴权 secret；文件不存在或内容无效时生成并写入（0600 权限）。

    无效文件（空文件、仅空白字符，如 touch 产生或写入中断残留）会被
    截断重写为新 secret；并发创建时另一进程已写入有效内容则直接复用。

    Args:
        secret_path: secret 文件路径，默认 ~/.xhs/bridge_secret。

    Returns:
        secret 原文（hex 字符串，64 字符）。
    """
    path = secret_path if secret_path is not None else SECRET_FILE
    existing = _read_secret(path)
    if existing is not None:
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # 并发创建：另一进程可能已写入有效内容，重读一次；
        # 仍无效（空文件/写入中断残留）则截断重写本进程的 secret
        existing = _read_secret(path)
        if existing is not None:
            return existing
        fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secret)
    return secret


def _read_secret(path: Path) -> str | None:
    """读取 secret 文件内容；不存在或 strip 后为空时返回 None（视为无效文件）。"""
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return content or None
