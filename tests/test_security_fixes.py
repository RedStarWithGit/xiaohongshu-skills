"""安全修复相关测试：URL 脱敏、bridge 鉴权 secret、server 握手鉴权。"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xhs.bridge_auth import get_bridge_secret
from xhs.errors import BridgeAuthError, CDPError, XHSError
from xhs.redact import redact_deep, redact_text, redact_url

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


# ─── redact_url ──────────────────────────────────────────────────────────────


def test_redact_url_masks_xsec_token() -> None:
    url = "https://www.xiaohongshu.com/explore/abc?xsec_token=SECRET123&xsec_source=pc_feed"
    out = redact_url(url)
    assert "SECRET123" not in out
    assert "xsec_source=pc_feed" in out
    assert "%3Credacted%3E" in out


def test_redact_url_preserves_other_params_and_order() -> None:
    url = "https://example.com/path?a=1&xsec_token=TOKEN&b=2"
    out = redact_url(url)
    assert "a=1" in out
    assert "b=2" in out
    assert "TOKEN" not in out
    assert out.index("a=1") < out.index("b=2")


def test_redact_url_no_query_unchanged() -> None:
    url = "https://www.xiaohongshu.com/explore/abc"
    assert redact_url(url) == url


def test_redact_url_invalid_returns_original() -> None:
    url = "http://[invalid"
    assert redact_url(url) == url


def test_redact_url_empty_value_keeps_placeholder() -> None:
    out = redact_url("https://example.com?xsec_token=")
    assert "%3Credacted%3E" in out


# ─── redact_text ─────────────────────────────────────────────────────────────


def test_redact_text_masks_long_token() -> None:
    text = (
        "请求失败: https://edith.xiaohongshu.com/api/sns/web/v1/feed"
        "?p1=1&xsec_token=ABCD12345678XYZ"
    )
    out = redact_text(text)
    assert "ABCD12345678XYZ" not in out
    assert "xsec_token=ABCD1234…" in out
    assert "p1=1" in out  # 其他 query 参数不受影响


def test_redact_text_masks_url_encoded_token() -> None:
    text = "redirect to /explore/abc?xsec_token=AB%2Fcd-Ef01_2345678"
    out = redact_text(text)
    assert "AB%2Fcd-Ef01_2345678" not in out
    assert out == "redirect to /explore/abc?xsec_token=AB%2Fcd-…"


def test_redact_text_empty_or_short_token_unchanged() -> None:
    # 空 token 值与不足 9 字符的值不做替换，避免破坏短字符串
    for text in ("xsec_token=", "xsec_token=ABC123", "xsec_token=12345678", "无 token 文本"):
        assert redact_text(text) == text


def test_redact_text_no_match_returns_original() -> None:
    text = "普通错误消息：与 bridge server 通信中断"
    assert redact_text(text) == text


# ─── redact_deep ─────────────────────────────────────────────────────────────


def test_redact_deep_dict_and_list_recursion() -> None:
    data = {
        "url": "https://www.xiaohongshu.com/explore/abc?xsec_token=TOKENVALUE12345678",
        "items": [
            {"detail": "failed: xsec_token=ABCD1234567890XYZ", "status": 404},
            "plain xsec_token=ABCD1234567890XYZ",
        ],
        "count": 2,
    }
    out = redact_deep(data)
    assert isinstance(out, dict)
    # 键名 url：redact_url 全量遮蔽 query 值，字段名保持不变
    assert "TOKENVALUE12345678" not in str(out)
    assert "%3Credacted%3E" in out["url"]
    assert out["url"].startswith("https://www.xiaohongshu.com/explore/abc?")
    # 普通键与列表内字符串：redact_text 保留前 8 字符
    assert out["items"][0]["detail"] == "failed: xsec_token=ABCD1234…"
    assert out["items"][1] == "plain xsec_token=ABCD1234…"
    # 非 str 类型原样返回
    assert out["items"][0]["status"] == 404
    assert out["count"] == 2


def test_redact_deep_sensitive_key_variants() -> None:
    token = "xsec_token=LONGTOKEN123456"
    data = {
        "pageUrl": f"https://xhslink.com/redirect?{token}",
        "redirectTo": f"https://www.xiaohongshu.com/explore/x?{token}",
        "location": f"https://www.xiaohongshu.com/explore/y?{token}",
        "redirect_source": f"https://www.xiaohongshu.com/explore/z?{token}",
        "final_url": f"https://www.xiaohongshu.com/explore/w?{token}",
    }
    out = str(redact_deep(data))
    assert "LONGTOKEN123456" not in out


def test_redact_deep_handles_cycle() -> None:
    a: dict = {"name": "a", "url": "https://e.com/p?xsec_token=CYCLICTOKEN12345"}
    b: dict = {"child": a}
    a["parent"] = b  # 循环引用
    out = redact_deep(a)
    assert out["name"] == "a"
    assert "CYCLICTOKEN12345" not in str(out)  # dict repr 自带循环保护，可安全 str()
    assert "%3Credacted%3E" in out["url"]


def test_redact_deep_depth_limit() -> None:
    # 深度 ≤ 6 层内正常脱敏，超过后原样返回
    leaf: dict = {"detail": "xsec_token=DEEPTOKEN1234567890"}
    deep: dict = leaf
    for _ in range(8):
        deep = {"child": deep}
    out = redact_deep(deep)
    node = out
    for _ in range(8):
        node = node["child"]
    # 第 7 层之后不再处理，叶子保持原文
    assert node is leaf
    assert node["detail"] == "xsec_token=DEEPTOKEN1234567890"


def test_redact_deep_passthrough_types() -> None:
    assert redact_deep(42) == 42
    assert redact_deep(None) is None
    assert redact_deep(True) is True
    # 顶层 str 也过 redact_text
    assert redact_deep("xsec_token=PLAINTEXTOKEN123") == "xsec_token=PLAINTEX…"


# ─── bridge_auth.get_bridge_secret ──────────────────────────────────────────


def test_get_bridge_secret_creates_hex_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "bridge_secret"
    secret = get_bridge_secret(secret_file)
    assert re.fullmatch(r"[0-9a-f]{64}", secret)
    # 文件内容为 UTF-8 文本、末尾无换行
    assert secret_file.read_text(encoding="utf-8") == secret


def test_get_bridge_secret_reads_existing(tmp_path: Path) -> None:
    secret_file = tmp_path / "bridge_secret"
    first = get_bridge_secret(secret_file)
    second = get_bridge_secret(secret_file)
    assert first == second


def test_get_bridge_secret_regenerates_empty_file(tmp_path: Path) -> None:
    # touch 产生或写入中断残留的空文件应视为无效并重生
    secret_file = tmp_path / "bridge_secret"
    secret_file.write_text("", encoding="utf-8")
    secret = get_bridge_secret(secret_file)
    assert re.fullmatch(r"[0-9a-f]{64}", secret)
    assert secret_file.read_text(encoding="utf-8") == secret


def test_get_bridge_secret_regenerates_whitespace_only_file(tmp_path: Path) -> None:
    # 仅含空白字符的文件 strip 后为空串，同样视为无效并重生
    secret_file = tmp_path / "bridge_secret"
    secret_file.write_text("   \n\t", encoding="utf-8")
    secret = get_bridge_secret(secret_file)
    assert re.fullmatch(r"[0-9a-f]{64}", secret)
    assert secret_file.read_text(encoding="utf-8") == secret


def test_get_bridge_secret_strips_whitespace_around_value(tmp_path: Path) -> None:
    # 含首尾空白的有效内容 strip 后正常使用，不触发重生
    secret_file = tmp_path / "bridge_secret"
    expected = "ab" * 32
    secret_file.write_text(f"  {expected}  \n", encoding="utf-8")
    assert get_bridge_secret(secret_file) == expected
    # 文件未被重写
    assert secret_file.read_text(encoding="utf-8") == f"  {expected}  \n"


def test_server_main_refuses_empty_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge_server = _load_bridge_server()

    def _fail_serve(*args: object, **kwargs: object) -> None:
        raise AssertionError("空 secret 时不应启动 websocket 服务")

    monkeypatch.setattr(bridge_server, "get_bridge_secret", lambda: "")
    monkeypatch.setattr(bridge_server.websockets, "serve", _fail_serve)
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(bridge_server.main(9333))
    assert exc_info.value.code == 1


# ─── bridge.py WebSocket 异常映射 ────────────────────────────────────────────


def test_bridge_call_wraps_websocket_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from websockets.exceptions import WebSocketException
    from xhs import bridge as bridge_mod

    class _FakeDrop(WebSocketException):
        """模拟 websockets 的 ConnectionClosed/TimeoutError 类异常。"""

    def _connect(*args: object, **kwargs: object) -> object:
        raise _FakeDrop("connection dropped")

    monkeypatch.setattr(bridge_mod.ws_client, "connect", _connect)
    page = bridge_mod.BridgePage()
    with pytest.raises(CDPError) as exc_info:
        page.evaluate("1+1")
    assert "与 bridge server 通信中断" in str(exc_info.value)
    assert isinstance(exc_info.value, XHSError)


# ─── BridgeAuthError ─────────────────────────────────────────────────────────


def test_bridge_auth_error_inherits_xhs_error() -> None:
    err = BridgeAuthError()
    assert isinstance(err, XHSError)
    assert "bridge_secret" in str(err)


# ─── bridge_server 握手鉴权 ─────────────────────────────────────────────────


class _FakeWS:
    """模拟首条消息的 WebSocket 连接（仅覆盖握手阶段）。"""

    def __init__(self, first_message: str) -> None:
        self._first = first_message
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> str:
        return self._first

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


def _load_bridge_server():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bridge_server", SCRIPTS_DIR / "bridge_server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_rejects_missing_auth() -> None:
    bridge_server = _load_bridge_server()
    server = bridge_server.BridgeServer("a" * 64)
    ws = _FakeWS(json.dumps({"role": "cli", "method": "ping_server"}))
    asyncio.run(server.handle(ws))
    assert ws.closed
    resp = json.loads(ws.sent[0])
    assert resp["type"] == "auth_error"
    assert "bridge_secret" in resp["message"]


def test_server_rejects_wrong_auth() -> None:
    bridge_server = _load_bridge_server()
    server = bridge_server.BridgeServer("a" * 64)
    ws = _FakeWS(json.dumps({"role": "cli", "auth": "b" * 64, "method": "ping_server"}))
    asyncio.run(server.handle(ws))
    assert ws.closed
    resp = json.loads(ws.sent[0])
    assert resp["type"] == "auth_error"


def test_server_accepts_valid_auth_ping() -> None:
    bridge_server = _load_bridge_server()
    secret = "c" * 64
    server = bridge_server.BridgeServer(secret)
    ws = _FakeWS(json.dumps({"role": "cli", "auth": secret, "method": "ping_server"}))
    asyncio.run(server.handle(ws))
    assert not ws.closed
    resp = json.loads(ws.sent[0])
    assert resp["result"]["extension_connected"] is False


class _HangingWS(_FakeWS):
    """模拟已建立长连接的扩展：注册后挂起，直到 release 被触发。"""

    def __init__(self, first_message: str) -> None:
        super().__init__(first_message)
        self.release = asyncio.Event()

    def __aiter__(self) -> _HangingWS:
        return self

    async def __anext__(self) -> str:
        await self.release.wait()
        raise StopAsyncIteration


def test_server_rejects_second_extension_connection() -> None:
    bridge_server = _load_bridge_server()
    secret = "d" * 64
    server = bridge_server.BridgeServer(secret)

    first = _HangingWS(json.dumps({"role": "extension", "auth": secret}))

    async def scenario() -> None:
        task = asyncio.ensure_future(server.handle(first))
        # 等待第一个扩展注册完成
        for _ in range(100):
            if server._extension_ws is not None:
                break
            await asyncio.sleep(0.01)
        assert server._extension_ws is not None

        second = _FakeWS(json.dumps({"role": "extension", "auth": secret}))
        await server.handle(second)
        assert second.closed
        resp = json.loads(second.sent[0])
        assert resp["type"] == "auth_error"
        assert "拒绝抢占" in resp["message"]

        # 释放第一个连接后，finally 置空，可再次接入
        first.release.set()
        await task
        assert server._extension_ws is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [json.dumps({"role": "cli", "auth": 123, "method": "ping_server"})],
)
def test_server_rejects_non_string_auth(payload: str) -> None:
    bridge_server = _load_bridge_server()
    server = bridge_server.BridgeServer("a" * 64)
    ws = _FakeWS(payload)
    asyncio.run(server.handle(ws))
    assert ws.closed
    resp = json.loads(ws.sent[0])
    assert resp["type"] == "auth_error"


def test_server_silently_drops_non_json_handshake() -> None:
    bridge_server = _load_bridge_server()
    server = bridge_server.BridgeServer("a" * 64)
    ws = _FakeWS("not-json")
    asyncio.run(server.handle(ws))
    # 无法解析的首条消息：直接丢弃，不响应也不登记
    assert ws.sent == []
    assert server._extension_ws is None
