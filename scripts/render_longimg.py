#!/usr/bin/env python3
"""Render an HTML long-image (750px wide) to a full-page PNG.

Usage: python3 render_longimg.py <input.html> <output.png> [scale]
Launches its own headless Chrome and connects via Playwright CDP,
so it never touches the user's daily Chrome profile.
"""
import subprocess, sys, time, socket, pathlib, urllib.request, json

HTML = pathlib.Path(sys.argv[1]).resolve()
OUT = pathlib.Path(sys.argv[2]).resolve()
SCALE = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

port = free_port()
chrome = subprocess.Popen([
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "--headless=new", f"--remote-debugging-port={port}",
    "--user-data-dir=/tmp/longimg-render-profile", "--no-first-run",
    "--hide-scrollbars", "about:blank",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1); break
        except Exception:
            time.sleep(0.2)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.new_context(viewport={"width": 750, "height": 1200}, device_scale_factor=SCALE)
        page = ctx.new_page()
        page.goto(HTML.as_uri())
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        height = page.evaluate("document.body.scrollHeight")
        page.screenshot(path=str(OUT), full_page=True)
        print(json.dumps({"out": str(OUT), "cssHeight": height, "scale": SCALE}))
finally:
    chrome.terminate()
