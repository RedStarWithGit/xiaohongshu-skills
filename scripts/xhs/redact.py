"""URL 日志脱敏工具：输出日志前移除敏感 query 参数值。

提供三个层级：
- redact_url: 单条 URL 的 query 参数脱敏
- redact_text: 任意文本中 xsec_token=<值> 模式脱敏
- redact_deep: dict/list 结构递归脱敏（防循环引用）
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

# 需要脱敏的敏感参数（值替换为 <redacted>，参数名保留）
_SENSITIVE_PARAMS = frozenset({"xsec_token"})

_REDACTED_PLACEHOLDER = "<redacted>"

# 文本级匹配 xsec_token=<值>：query 值常见形态（含 URL 编码字符），≥9 字符才算有效值
_TEXT_TOKEN_PATTERN = re.compile(r"xsec_token=([A-Za-z0-9_%\-]{9,})")

# redact_deep 中 str 值需额外过 redact_url 的键名（大小写不敏感）
_SENSITIVE_KEYS = frozenset(
    {"url", "final_url", "pageurl", "redirect_source", "redirectto", "location"}
)

_MAX_DEPTH = 6


def redact_url(url: str) -> str:
    """将 URL query 中敏感参数（如 xsec_token）的值替换为 <redacted>。

    非破坏性：解析失败时原样返回，不影响正常 URL。

    Args:
        url: 原始 URL。

    Returns:
        脱敏后的 URL。
    """
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return url

    if not query:
        return url

    redacted = [
        (key, _REDACTED_PLACEHOLDER if key in _SENSITIVE_PARAMS else value) for key, value in query
    ]
    new_query = urllib.parse.urlencode(redacted)
    return urllib.parse.urlunsplit(parts._replace(query=new_query))


def redact_text(text: str) -> str:
    """文本级脱敏：替换文本中所有 xsec_token=<值> 模式的值为前 8 字符 + …。

    覆盖 URL 编码形式的 token 值（%XX 转义字符也计入匹配）；
    无匹配时原样返回，非破坏性。

    Args:
        text: 原始文本（完整 URL、错误消息或日志片段均可）。

    Returns:
        脱敏后的文本。
    """
    return _TEXT_TOKEN_PATTERN.sub(lambda m: f"xsec_token={m.group(1)[:8]}…", text)


def redact_deep(obj: Any) -> Any:
    """递归脱敏任意 JSON 兼容结构。

    dict/list 逐层遍历：str 值先过 redact_text；键名为 url/final_url/
    pageUrl/redirect_source/redirectTo/location 的 str 值额外过 redact_url。
    其他类型原样返回。防循环引用（id → 已处理副本映射，循环引用指向
    脱敏后的副本），深度 ≤ 6 层，超深原样返回。

    Args:
        obj: 待脱敏对象（dict/list/str/标量均可）。

    Returns:
        脱敏后的同构对象。
    """
    return _redact_deep(obj, depth=0, memo={})


def _redact_deep(obj: Any, depth: int, memo: dict[int, Any]) -> Any:
    """redact_deep 的递归实现；memo 防循环引用与重复处理。"""
    if depth > _MAX_DEPTH:
        return obj
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict | list):
        if id(obj) in memo:
            return memo[id(obj)]
        result: Any = {} if isinstance(obj, dict) else []
        memo[id(obj)] = result  # 先占位，循环引用会指向这份脱敏副本
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                        # 先文本脱敏兜底（覆盖非 query 位置的 token），再按 URL 规则全量遮蔽
                        value = redact_url(redact_text(value))
                    else:
                        value = redact_text(value)
                elif isinstance(value, dict | list):
                    value = _redact_deep(value, depth + 1, memo)
                result[key] = value
        else:
            for item in obj:
                if isinstance(item, str):
                    result.append(redact_text(item))
                elif isinstance(item, dict | list):
                    result.append(_redact_deep(item, depth + 1, memo))
                else:
                    result.append(item)
        return result
    return obj
