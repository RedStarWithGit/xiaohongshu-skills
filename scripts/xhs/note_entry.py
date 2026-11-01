"""笔记详情进入入口：优先模拟"搜索结果页点击卡片"，失败兜底 URL 直达。

人类进入一篇笔记的自然路径是：搜索关键词 → 浏览结果列表 → 点击卡片。
直接 navigate(详情 URL) 的行为特征明显（无列表页上下文、整页刷新），
容易被风控识别。本模块将"进入笔记"改为模拟真人路径：

1. 当前页已保有搜索结果（SPA state 未销毁）→ 关闭笔记弹窗后直接点下一张卡片，不重新加载
2. 否则导航到搜索结果页 → 等待结果就绪 → 滚动定位卡片 → CDP 真实点击（isTrusted=true）
3. 卡片不在该关键词结果中 / 点击流程异常 → 兜底 URL 直达（保留原重试逻辑）
"""

from __future__ import annotations

import json
import logging
import random
import time

from .cdp import Page
from .errors import PageNotAccessibleError
from .human import HOVER_TIME, REACTION_TIME, sleep_random
from .redact import redact_url
from .selectors import NOTE_MODAL_CLOSE
from .urls import make_feed_detail_url, make_search_url

logger = logging.getLogger(__name__)

# 等待搜索结果 state 就绪（秒）
_SEARCH_STATE_TIMEOUT = 15.0
# 点击卡片后等待笔记详情出现（秒）
_NOTE_OPEN_TIMEOUT = 12.0
# 页面内找不到卡片时向下滚动的次数
_SCROLL_FIND_ATTEMPTS = 3

# 当前页是否仍保有搜索结果（连续看帖时免重新加载）
_HAS_SEARCH_STATE_JS = """
(() => {
    const s = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.search;
    if (!s || !s.feeds) return false;
    const v = s.feeds.value !== undefined ? s.feeds.value : s.feeds._value;
    return Array.isArray(v) && v.length > 0;
})()
"""

# 当前笔记详情弹窗是否已打开（返回已加载的 noteId 列表）
_NOTE_STATE_JS = """
(() => {
    const m = window.__INITIAL_STATE__ &&
              window.__INITIAL_STATE__.note &&
              window.__INITIAL_STATE__.note.noteDetailMap;
    if (!m) return "";
    return Object.keys(m).join(",");
})()
"""


def open_note_detail(page: Page, feed_id: str, xsec_token: str, keyword: str = "") -> bool:
    """进入笔记详情页。

    Args:
        page: 页面对象（BridgePage 或 CDP Page，接口兼容）。
        feed_id: Feed ID。
        xsec_token: xsec_token（URL 兜底路径使用）。
        keyword: 搜索关键词。提供时优先走"搜索页点击卡片"路径；
            为空时直接 URL 进入（保持旧行为）。

    Returns:
        True=通过点击卡片进入，False=URL 直达。

    Raises:
        PageNotAccessibleError: URL 直达时被风控拦截。
        RuntimeError: 页面导航失败。
    """
    if keyword:
        try:
            if _open_by_click(page, feed_id, keyword):
                return True
            logger.info("搜索结果中未找到笔记卡片，改用 URL 直达")
        except Exception as e:
            logger.warning("点击进入失败（%s），改用 URL 直达", e)
    _open_by_url(page, feed_id, xsec_token)
    return False


# ========== 点击进入路径 ==========


def _open_by_click(page: Page, feed_id: str, keyword: str) -> bool:
    """模拟真人：打开搜索结果页，浏览并点击目标笔记卡片。成功返回 True。"""
    has_state = False
    try:
        has_state = page.evaluate(_HAS_SEARCH_STATE_JS) is True
    except Exception as e:
        logger.debug("检查搜索结果 state 失败: %s", e)

    if has_state:
        logger.info("当前页已有搜索结果，关闭弹窗后直接点击卡片（不重新加载）")
        page.scroll_to(0, 0)
        _close_note_modal_if_open(page)
    else:
        search_url = make_search_url(keyword)
        logger.info("打开搜索结果页: %s", redact_url(search_url))
        page.navigate(search_url)
        page.wait_for_load()
        page.wait_dom_stable()
        _wait_search_state(page)

    sleep_random(600, 1400)

    card = _find_visible_card(page, feed_id)
    if card is None:
        return False

    _human_click(page, card)
    if not _wait_note_opened(page, feed_id):
        logger.warning("点击卡片后笔记详情未打开")
        return False
    sleep_random(600, 1200)
    logger.info("已通过点击进入笔记: %s", feed_id)
    return True


def _wait_search_state(page: Page) -> None:
    """等待搜索结果 __INITIAL_STATE__ 就绪。"""
    deadline = time.monotonic() + _SEARCH_STATE_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if page.evaluate(_HAS_SEARCH_STATE_JS) is True:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError("搜索结果加载超时")


def _find_visible_card(page: Page, feed_id: str) -> dict | None:
    """查找目标笔记的可见卡片链接，必要时模拟人向下滚动查找。

    Returns:
        {"x": 中心x, "y": 中心y, "href": 链接}；未找到返回 None。
    """
    find_js = f"""
(() => {{
    const nid = {json.dumps(feed_id)};
    const links = Array.from(document.querySelectorAll('a[href*="' + nid + '"]'));
    for (const a of links) {{
        const rect = a.getBoundingClientRect();
        if (rect.width < 80 || rect.height < 80) continue;
        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
        return {{x: Math.round(rect.left + rect.width / 2),
                y: Math.round(rect.top + rect.height / 2),
                href: a.href || ''}};
    }}
    return null;
}})()
"""
    for attempt in range(_SCROLL_FIND_ATTEMPTS):
        info = page.evaluate(find_js)
        if isinstance(info, dict) and info.get("x") is not None:
            if attempt > 0:
                sleep_random(400, 900)
            return info
        if attempt < _SCROLL_FIND_ATTEMPTS - 1:
            logger.debug("卡片未找到，向下滚动继续找 (#%d)", attempt + 1)
            delta = int(page.get_viewport_height() * random.uniform(0.6, 0.9))
            page.scroll_by(0, delta)
            sleep_random(500, 1000)
    return None


def _human_click(page: Page, card: dict) -> None:
    """模拟真人点击：鼠标先移到卡片附近，停顿后移入并点击（CDP 真实输入事件）。"""
    x = float(card["x"]) + random.uniform(-6, 6)
    y = float(card["y"]) + random.uniform(-6, 6)
    page.mouse_move(x + random.uniform(-25, 25), y + random.uniform(-25, 25))
    sleep_random(*REACTION_TIME)
    page.mouse_move(x, y)
    sleep_random(*HOVER_TIME)
    page.mouse_click(x, y)


def _wait_note_opened(page: Page, feed_id: str) -> bool:
    """等待笔记详情在 __INITIAL_STATE__.note.noteDetailMap 中出现。"""
    deadline = time.monotonic() + _NOTE_OPEN_TIMEOUT
    while time.monotonic() < deadline:
        try:
            keys = page.evaluate(_NOTE_STATE_JS) or ""
            if feed_id in keys.split(","):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _close_note_modal_if_open(page: Page) -> None:
    """若当前有笔记弹窗（刚看完上一篇），先关闭回到结果列表。"""
    try:
        if page.has_element(NOTE_MODAL_CLOSE):
            page.click_element(NOTE_MODAL_CLOSE)
            sleep_random(500, 1000)
            logger.debug("已关闭上一篇笔记弹窗")
    except Exception as e:
        logger.debug("关闭笔记弹窗失败（忽略）: %s", e)


# ========== URL 直达路径（兜底） ==========


def _open_by_url(page: Page, feed_id: str, xsec_token: str) -> None:
    """URL 直达详情页（兜底）。含瞬态错误重试；风控拦截直接抛出。

    注：风控 302→/404 由扩展 auto-fix（自动从搜索页换新 token 重试），
    此处只捕获真正的瞬态错误（网络超时等），风控拦截不重试。
    """
    url = make_feed_detail_url(feed_id, xsec_token)
    logger.info("URL 直达详情页: %s", redact_url(url))
    for attempt in range(3):
        try:
            page.navigate(url)
            page.wait_for_load()
            page.wait_dom_stable()
            return
        except Exception as e:
            err_str = str(e)
            # 风控 302 重定向：扩展已尝试 auto-fix，仍失败说明 token/session 问题
            if "风控拦截" in err_str or "重定向至" in err_str:
                raise PageNotAccessibleError(f"笔记无法访问（风控/token）: {err_str}") from e
            logger.debug("页面导航重试 #%d: %s", attempt, e)
            time.sleep(0.5 + random.random())
    raise RuntimeError("页面导航失败")
