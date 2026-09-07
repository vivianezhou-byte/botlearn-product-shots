#!/usr/bin/env python3
"""启动、检查和停止 BotLearn 走查专用的独立浏览器会话。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - 浏览器走查仅支持 macOS/Linux
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = "botlearn-browser-session/1.1"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LOCK_PATH = Path(tempfile.gettempdir()) / "botlearn-walkthrough-browser-port.lock"
BROWSER_CANDIDATES = (
    Path(
        "/Applications/Google Chrome for Testing.app/Contents/MacOS/"
        "Google Chrome for Testing"
    ),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
)

_IO_SPEC = importlib.util.spec_from_file_location(
    "walkthrough_io_utils", Path(__file__).resolve().parent / "io_utils.py"
)
assert _IO_SPEC and _IO_SPEC.loader
io_utils = importlib.util.module_from_spec(_IO_SPEC)
_IO_SPEC.loader.exec_module(io_utils)


class BrowserSessionError(RuntimeError):
    """浏览器会话无法安全启动或停止。"""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    io_utils.atomic_write_json(path, data)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BrowserSessionError(f"找不到会话清单：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BrowserSessionError(f"会话清单不是合法 JSON：{error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise BrowserSessionError(f"会话清单 schemaVersion 必须是 {SCHEMA_VERSION}")
    return value


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise BrowserSessionError(
            "session id 只能包含字母、数字、点、下划线和连字号，长度不超过 64"
        )
    return session_id


def default_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"worker-{stamp}-{os.getpid()}-{uuid4().hex[:6]}"


def find_browser(explicit: Path | None = None) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise BrowserSessionError(f"浏览器不存在或不可执行：{candidate}")
        return candidate
    for candidate in BROWSER_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()
    raise BrowserSessionError(
        "未找到 Chrome for Testing、Google Chrome 或 Chromium；"
        "用 --browser 传入可执行文件路径"
    )


def browser_command(
    browser: Path, *, port: int, profile_dir: Path, entry_url: str
) -> list[str]:
    return [
        str(browser),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        entry_url,
    ]


def _available_port(requested: int) -> int:
    if requested < 0 or requested > 65535:
        raise BrowserSessionError("--port 必须是 0 或 1–65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", requested))
        except OSError as error:
            raise BrowserSessionError(
                f"本地端口 {requested} 不可用：{error}"
            ) from error
        return int(probe.getsockname()[1])


@contextmanager
def _port_allocation_lock() -> Iterator[None]:
    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("r+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def devtools_ready(port: int, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=timeout
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait_until_ready(
    process: subprocess.Popen[bytes],
    port: int,
    wait_seconds: float,
    probe: Callable[[int], bool],
) -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise BrowserSessionError(f"浏览器在就绪前退出，退出码 {exit_code}")
        if probe(port):
            return
        time.sleep(0.2)
    raise BrowserSessionError(f"浏览器未在 {wait_seconds:g} 秒内开放 CDP 端口 {port}")


def start_session(
    root_dir: Path,
    *,
    entry_url: str,
    session_id: str | None = None,
    browser_path: Path | None = None,
    port: int = 0,
    wait_seconds: float = 20.0,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    readiness_probe: Callable[[int], bool] = devtools_ready,
) -> dict[str, Any]:
    session_id = validate_session_id(session_id or default_session_id())
    if wait_seconds <= 0:
        raise BrowserSessionError("--wait-seconds 必须大于 0")
    browser = find_browser(browser_path)
    session_dir = root_dir.resolve() / "browser-sessions" / session_id
    if session_dir.exists():
        raise BrowserSessionError(
            f"会话目录已存在：{session_dir}；请换一个 --session-id"
        )
    profile_dir = session_dir / "profile"
    profile_dir.mkdir(parents=True)
    log_path = session_dir / "browser.log"

    with _port_allocation_lock():
        selected_port = _available_port(port)
        command = browser_command(
            browser,
            port=selected_port,
            profile_dir=profile_dir,
            entry_url=entry_url,
        )
        with log_path.open("ab") as log_handle:
            process = popen_factory(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            _wait_until_ready(process, selected_port, wait_seconds, readiness_probe)
        except BrowserSessionError:
            if process.poll() is None:
                process.terminate()
            raise

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "launchId": uuid4().hex,
        "status": "running",
        "profileMode": "fresh",
        "pid": process.pid,
        "browserPath": str(browser),
        "port": selected_port,
        "cdpUrl": f"http://127.0.0.1:{selected_port}",
        "profileDir": str(profile_dir),
        "entryUrl": entry_url,
        "startedAt": _now_iso(),
        "stoppedAt": "",
        "logPath": str(log_path),
    }
    _write_json(session_dir / "browser.json", manifest)
    return manifest


def _process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def process_matches_manifest(manifest: dict[str, Any]) -> bool:
    pid = manifest.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    command = _process_command(pid)
    return bool(
        command
        and f"--remote-debugging-port={manifest.get('port')}" in command
        and f"--user-data-dir={manifest.get('profileDir')}" in command
    )


def assert_isolated_session(
    manifest_path: Path, *, require_live: bool = True
) -> dict[str, Any]:
    """Validate that a manifest owns a fresh, dedicated browser process."""
    manifest_path = manifest_path.expanduser().resolve()
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "running":
        raise BrowserSessionError("独立浏览器会话不是 running 状态")
    if manifest.get("profileMode") != "fresh":
        raise BrowserSessionError("profileMode 必须是 fresh")
    launch_id = manifest.get("launchId")
    if not isinstance(launch_id, str) or not launch_id:
        raise BrowserSessionError("launchId 必须是非空字符串")
    expected_profile = (manifest_path.parent / "profile").resolve()
    profile_value = manifest.get("profileDir")
    if (
        not isinstance(profile_value, str)
        or Path(profile_value).resolve() != expected_profile
    ):
        raise BrowserSessionError(
            f"profileDir 必须是 browser.json 同目录的 profile：{expected_profile}"
        )
    port = manifest.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise BrowserSessionError("port 必须是 1–65535")
    if manifest.get("cdpUrl") != f"http://127.0.0.1:{port}":
        raise BrowserSessionError("cdpUrl 与会话端口不一致")
    if require_live and not process_matches_manifest(manifest):
        raise BrowserSessionError("browser.json 不对应当前运行的独立浏览器进程")
    if require_live and not devtools_ready(port):
        raise BrowserSessionError("独立浏览器的 CDP 端口不可用")
    return manifest


def stop_session(manifest_path: Path, *, wait_seconds: float = 10.0) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("status") == "stopped":
        return manifest
    if not process_matches_manifest(manifest):
        raise BrowserSessionError(
            "清单中的 PID 不再对应该浏览器会话，为避免误杀进程已拒绝停止"
        )
    pid = int(manifest["pid"])
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline and _process_command(pid):
        time.sleep(0.2)
    if _process_command(pid):
        raise BrowserSessionError(
            f"浏览器 PID {pid} 在 {wait_seconds:g} 秒内未退出；未强制结束"
        )
    manifest["status"] = "stopped"
    manifest["stoppedAt"] = _now_iso()
    _write_json(manifest_path, manifest)
    return manifest


def session_status(manifest_path: Path) -> dict[str, Any]:
    manifest = dict(_read_json(manifest_path))
    manifest["processMatches"] = process_matches_manifest(manifest)
    manifest["devtoolsReady"] = devtools_ready(int(manifest.get("port", 0)))
    try:
        assert_isolated_session(manifest_path, require_live=False)
        manifest["isolationValid"] = True
    except BrowserSessionError as error:
        manifest["isolationValid"] = False
        manifest["isolationError"] = str(error)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="启动独立测试浏览器")
    start.add_argument("root_dir", type=Path)
    start.add_argument("--entry-url", required=True)
    start.add_argument("--session-id", default="")
    start.add_argument("--browser", type=Path)
    start.add_argument("--port", type=int, default=0, help="0 表示自动分配")
    start.add_argument("--wait-seconds", type=float, default=20.0)

    stop = subparsers.add_parser("stop", help="停止会话，保留 profile 与日志")
    stop.add_argument("manifest", type=Path)
    stop.add_argument("--wait-seconds", type=float, default=10.0)

    status = subparsers.add_parser("status", help="查看会话进程和 CDP 状态")
    status.add_argument("manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            manifest = start_session(
                args.root_dir,
                entry_url=args.entry_url,
                session_id=args.session_id or None,
                browser_path=args.browser,
                port=args.port,
                wait_seconds=args.wait_seconds,
            )
        elif args.command == "stop":
            manifest = stop_session(args.manifest, wait_seconds=args.wait_seconds)
        else:
            manifest = session_status(args.manifest)
    except (BrowserSessionError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
