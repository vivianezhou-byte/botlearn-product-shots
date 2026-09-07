#!/usr/bin/env python3
"""通过 browser.json 强绑定的 Playwright-over-CDP 控制独立 Chrome。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent

_SESSION_SPEC = importlib.util.spec_from_file_location(
    "walkthrough_browser_session", SCRIPT_DIR / "browser_session.py"
)
assert _SESSION_SPEC and _SESSION_SPEC.loader
browser_session = importlib.util.module_from_spec(_SESSION_SPEC)
_SESSION_SPEC.loader.exec_module(browser_session)

_IO_SPEC = importlib.util.spec_from_file_location(
    "walkthrough_io_utils", SCRIPT_DIR / "io_utils.py"
)
assert _IO_SPEC and _IO_SPEC.loader
io_utils = importlib.util.module_from_spec(_IO_SPEC)
_IO_SPEC.loader.exec_module(io_utils)


ROLE_PATTERN = re.compile(
    r"^role=([A-Za-z][A-Za-z0-9_-]*)"
    r"(?:\[name=(?:\"([^\"]*)\"|'([^']*)'|([^\]]+))\])?$"
)
LOCATOR_PREFIXES = {
    "alt": "get_by_alt_text",
    "label": "get_by_label",
    "placeholder": "get_by_placeholder",
    "testid": "get_by_test_id",
    "text": "get_by_text",
    "title": "get_by_title",
}


class ControlError(RuntimeError):
    """无法安全控制清单指定的浏览器。"""


def _playwright_factory() -> Callable[[], Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise ControlError(
            "缺少 Playwright；先按 Skill requirements.txt 安装依赖"
        ) from error
    return sync_playwright


def assert_isolated_session(manifest_path: Path) -> dict[str, Any]:
    """拒绝任何不是由 browser.json 所有的全新会话。"""
    try:
        return browser_session.assert_isolated_session(manifest_path)
    except browser_session.BrowserSessionError as error:
        raise ControlError(str(error)) from error


class PlaywrightController:
    """连接清单 CDP 端点，但不拥有 Chrome 生命周期。"""

    def __init__(
        self,
        manifest: dict[str, Any],
        *,
        playwright_factory: Callable[[], Any] | None = None,
        connect_timeout_ms: float = 60_000,
    ) -> None:
        self.manifest = manifest
        self.playwright_factory = playwright_factory
        self.connect_timeout_ms = connect_timeout_ms
        self.manager: Any = None
        self.runtime: Any = None
        self.browser: Any = None

    def connect(self) -> None:
        factory = self.playwright_factory or _playwright_factory()
        try:
            self.manager = factory()
            self.runtime = self.manager.start()
            self.browser = self.runtime.chromium.connect_over_cdp(
                self.manifest["cdpUrl"], timeout=self.connect_timeout_ms
            )
        except Exception as error:
            self.close()
            raise ControlError(f"Playwright 无法连接清单 CDP 端点：{error}") from error
        if not self.browser.contexts:
            self.close()
            raise ControlError("独立浏览器没有可用 BrowserContext")

    def close(self) -> None:
        # 不调用 browser.close()；Chrome 只能由 browser_session.py stop 停止。
        if self.manager is not None:
            with suppress(Exception):
                self.manager.stop()
            self.manager = None

    def page_entries(self) -> list[tuple[Any, Any]]:
        if self.browser is None:
            raise ControlError("Playwright 尚未连接")
        return [
            (context, page)
            for context in self.browser.contexts
            for page in context.pages
            if not str(page.url).startswith("devtools://")
        ]

    @staticmethod
    def target_id(context: Any, page: Any) -> str:
        session = context.new_cdp_session(page)
        try:
            result = session.send("Target.getTargetInfo")
        finally:
            session.detach()
        return str(result.get("targetInfo", {}).get("targetId", ""))

    def page_records(self) -> list[dict[str, Any]]:
        return [
            {
                "index": index,
                "targetId": self.target_id(context, page),
                "title": page.title(),
                "url": page.url,
            }
            for index, (context, page) in enumerate(self.page_entries())
        ]

    def select_page(
        self, *, target_id: str = "", page_index: int | None = None
    ) -> tuple[Any, Any]:
        entries = self.page_entries()
        if not entries:
            raise ControlError("独立浏览器没有可控制的 page")
        if page_index is not None:
            if page_index < 0 or page_index >= len(entries):
                raise ControlError(
                    f"--page-index 超出范围：{page_index}（共 {len(entries)} 页）"
                )
            return entries[page_index]
        if target_id:
            for context, page in entries:
                if self.target_id(context, page) == target_id:
                    return context, page
            raise ControlError(f"找不到 page target：{target_id}")
        return entries[0]


def resolve_scope(page: Any, frame_selectors: list[str]) -> Any:
    """逐层进入 iframe，返回 Page 或 FrameLocator。"""
    scope = page
    for selector in frame_selectors:
        if not selector.strip():
            raise ControlError("--frame 不能是空字符串")
        scope = scope.frame_locator(selector)
    return scope


def resolve_locator(scope: Any, specification: str) -> Any:
    """将紧凑、可读的定位字符串转为 Playwright Locator。"""
    if not specification.strip():
        raise ControlError("元素定位字符串不能为空")
    role_match = ROLE_PATTERN.fullmatch(specification)
    if role_match:
        role = role_match.group(1)
        name = next(
            (value for value in role_match.groups()[1:] if value is not None), None
        )
        if name is None:
            return scope.get_by_role(role)
        return scope.get_by_role(role, name=name, exact=True)
    if specification.startswith("role="):
        raise ControlError('角色定位格式必须是 role=button 或 role=button[name="提交"]')
    if "=" in specification:
        prefix, value = specification.split("=", 1)
        if prefix == "css":
            if not value:
                raise ControlError("css= 后必须提供选择器")
            return scope.locator(value)
        method_name = LOCATOR_PREFIXES.get(prefix)
        if method_name is not None:
            if not value:
                raise ControlError(f"{prefix}= 后必须提供文本")
            method = getattr(scope, method_name)
            if prefix == "testid":
                return method(value)
            return method(value, exact=True)
    return scope.locator(specification)


def _add_locator_command(
    subparsers: Any, name: str, help_text: str
) -> argparse.ArgumentParser:
    command = subparsers.add_parser(name, help=help_text)
    command.add_argument("locator", help="CSS 或语义定位字符串")
    return command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest", type=Path, help="browser_session.py 生成的 browser.json"
    )
    page_selector = parser.add_mutually_exclusive_group()
    page_selector.add_argument(
        "--target-id", default="", help="指定 CDP page target id"
    )
    page_selector.add_argument("--page-index", type=int, help="指定 tabs 输出的页索引")
    parser.add_argument(
        "--frame",
        action="append",
        default=[],
        help="按 CSS 选择器逐层进入 iframe，可重复",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="动作超时秒数，默认 30"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="校验会话、Playwright 连接和 page")
    subparsers.add_parser("tabs", help="列出当前实例的 page")

    read = subparsers.add_parser("read", help="读取当前页标题、地址与正文")
    read.add_argument("--max-chars", type=int, default=5000)

    snapshot = subparsers.add_parser("snapshot", help="输出可访问性语义快照")
    snapshot.add_argument("locator", nargs="?", default="body")

    navigate = subparsers.add_parser("navigate", help="导航当前 page")
    navigate.add_argument("url")
    navigate.add_argument(
        "--wait-until",
        choices=("commit", "domcontentloaded", "load", "networkidle"),
        default="domcontentloaded",
    )

    evaluate = subparsers.add_parser("evaluate", help="在当前 page 执行 JavaScript")
    evaluate.add_argument("expression")
    evaluate.add_argument(
        "--await-promise",
        action="store_true",
        help="为旧 CLI 保留；Playwright 会自动等待 Promise",
    )

    click = _add_locator_command(subparsers, "click", "点击元素")
    click.add_argument("--wait", type=float, default=0.0, help="点击后额外等待秒数")

    fill = _add_locator_command(subparsers, "type", "清空并填入元素")
    fill.add_argument("text")

    press = subparsers.add_parser("press", help="向页面或元素发送按键")
    press.add_argument("key")
    press.add_argument("--locator", default="")

    _add_locator_command(subparsers, "hover", "悬停在元素上")
    _add_locator_command(subparsers, "check", "选中 checkbox 或 radio")
    _add_locator_command(subparsers, "uncheck", "取消选中 checkbox")

    select = _add_locator_command(subparsers, "select", "选择 select 的 value")
    select.add_argument("values", nargs="+")

    wait_for = _add_locator_command(subparsers, "wait-for", "等待元素状态")
    wait_for.add_argument(
        "--state",
        choices=("attached", "detached", "hidden", "visible"),
        default="visible",
    )

    resize = subparsers.add_parser("resize", help="设置视口尺寸")
    resize.add_argument("width", type=int)
    resize.add_argument("height", type=int)
    resize.add_argument("--scale", type=float, default=1.0)

    screenshot = subparsers.add_parser("screenshot", help="原子保存 PNG 截图")
    screenshot.add_argument("output", type=Path)
    screenshot.add_argument("--full-page", action="store_true")

    console = subparsers.add_parser("console", help="收集控制台与失败请求")
    console.add_argument("--wait", type=float, default=1.0)

    open_tab = subparsers.add_parser("open-tab", help="在同一独立实例打开新 page")
    open_tab.add_argument("url", nargs="?", default="about:blank")

    subparsers.add_parser("close-tab", help="关闭当前选中的 page")

    download = _add_locator_command(subparsers, "download", "点击并保存下载")
    download.add_argument("output", type=Path)
    return parser


def _timeout_ms(args: argparse.Namespace) -> float:
    if args.timeout <= 0:
        raise ControlError("--timeout 必须大于 0")
    return args.timeout * 1000


def _atomic_save_download(download: Any, output: Path) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        download.save_as(temporary)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _console_events(page: Any, wait_seconds: float) -> dict[str, Any]:
    console: list[dict[str, Any]] = []
    network_errors: list[dict[str, Any]] = []

    def on_console(message: Any) -> None:
        console.append({"type": message.type, "text": message.text[:2000]})

    def on_page_error(error: Any) -> None:
        console.append({"type": "exception", "text": str(error)[:2000]})

    def on_response(response: Any) -> None:
        if response.status >= 400:
            network_errors.append(
                {"status": response.status, "url": response.url[:500]}
            )

    def on_request_failed(request: Any) -> None:
        network_errors.append({"status": "requestfailed", "url": request.url[:500]})

    handlers = (
        ("console", on_console),
        ("pageerror", on_page_error),
        ("response", on_response),
        ("requestfailed", on_request_failed),
    )
    for event, handler in handlers:
        page.on(event, handler)
    try:
        page.wait_for_timeout(max(wait_seconds, 0) * 1000)
    finally:
        for event, handler in handlers:
            page.remove_listener(event, handler)
    return {"console": console, "networkErrors": network_errors}


def execute_command(
    controller: PlaywrightController, args: argparse.Namespace
) -> dict[str, Any]:
    timeout = _timeout_ms(args)
    if args.command in {"status", "tabs"}:
        return {
            "sessionId": controller.manifest["sessionId"],
            "launchId": controller.manifest["launchId"],
            "cdpUrl": controller.manifest["cdpUrl"],
            "profileDir": controller.manifest["profileDir"],
            "controlEngine": "playwright-over-cdp",
            "pages": controller.page_records(),
        }

    if args.command == "open-tab":
        context = controller.browser.contexts[0]
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=timeout)
        return {
            "targetId": controller.target_id(context, page),
            "title": page.title(),
            "url": page.url,
        }

    context, page = controller.select_page(
        target_id=args.target_id, page_index=args.page_index
    )
    target_id = controller.target_id(context, page)
    if args.command == "close-tab":
        page.close()
        return {"targetId": target_id, "closed": True}

    scope = resolve_scope(page, args.frame)
    if args.command == "read":
        if args.max_chars < 1:
            raise ControlError("--max-chars 必须是正整数")
        text = scope.locator("body").inner_text(timeout=timeout)
        return {
            "targetId": target_id,
            "page": {
                "title": page.title(),
                "url": page.url,
                "text": text[: args.max_chars],
            },
        }
    if args.command == "snapshot":
        snapshot = resolve_locator(scope, args.locator).aria_snapshot(timeout=timeout)
        return {"targetId": target_id, "snapshot": snapshot}
    if args.command == "navigate":
        if args.frame:
            raise ControlError("navigate 不接受 --frame；请直接导航 page")
        page.goto(args.url, wait_until=args.wait_until, timeout=timeout)
        return {"targetId": target_id, "title": page.title(), "url": page.url}
    if args.command == "evaluate":
        if args.frame:
            raise ControlError("evaluate 不接受 --frame；请在 page 上执行")
        return {"targetId": target_id, "value": page.evaluate(args.expression)}
    if args.command == "click":
        resolve_locator(scope, args.locator).click(timeout=timeout)
        if args.wait > 0:
            page.wait_for_timeout(args.wait * 1000)
        return {"targetId": target_id, "clicked": args.locator, "url": page.url}
    if args.command == "type":
        resolve_locator(scope, args.locator).fill(args.text, timeout=timeout)
        return {"targetId": target_id, "filled": args.locator}
    if args.command == "press":
        if args.locator:
            resolve_locator(scope, args.locator).press(args.key, timeout=timeout)
        else:
            page.keyboard.press(args.key)
        return {"targetId": target_id, "key": args.key}
    if args.command == "hover":
        resolve_locator(scope, args.locator).hover(timeout=timeout)
        return {"targetId": target_id, "hovered": args.locator}
    if args.command in {"check", "uncheck"}:
        locator = resolve_locator(scope, args.locator)
        getattr(locator, args.command)(timeout=timeout)
        return {"targetId": target_id, args.command: args.locator}
    if args.command == "select":
        selected = resolve_locator(scope, args.locator).select_option(
            value=args.values, timeout=timeout
        )
        return {"targetId": target_id, "selected": selected}
    if args.command == "wait-for":
        resolve_locator(scope, args.locator).wait_for(state=args.state, timeout=timeout)
        return {"targetId": target_id, "locator": args.locator, "state": args.state}
    if args.command == "resize":
        if args.width < 1 or args.height < 1 or args.scale <= 0:
            raise ControlError("视口尺寸和 scale 必须大于 0")
        session = context.new_cdp_session(page)
        try:
            session.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": args.width,
                    "height": args.height,
                    "deviceScaleFactor": args.scale,
                    "mobile": False,
                },
            )
        finally:
            session.detach()
        return {"width": args.width, "height": args.height, "scale": args.scale}
    if args.command == "screenshot":
        image = page.screenshot(full_page=args.full_page, timeout=timeout)
        io_utils.atomic_write_bytes(args.output, image)
        return {"output": str(args.output.resolve()), "targetId": target_id}
    if args.command == "console":
        return {"targetId": target_id, **_console_events(page, args.wait)}
    if args.command == "download":
        with page.expect_download(timeout=timeout) as download_info:
            resolve_locator(scope, args.locator).click(timeout=timeout)
        _atomic_save_download(download_info.value, args.output)
        return {
            "targetId": target_id,
            "output": str(args.output.expanduser().resolve()),
            "suggestedFilename": download_info.value.suggested_filename,
        }
    raise ControlError(f"未支持的命令：{args.command}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = assert_isolated_session(args.manifest)
    controller = PlaywrightController(manifest)
    controller.connect()
    try:
        return execute_command(controller, args)
    except ControlError:
        raise
    except Exception as error:
        if error.__class__.__module__.startswith("playwright"):
            raise ControlError(f"Playwright 操作失败：{error}") from error
        raise
    finally:
        controller.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (ControlError, OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
