"""Render isolated design files in a fresh headless Edge profile, using Tokyo Python."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
OUT = ROOT / "output" / "mobile-japanese-design"
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
ROUTES = ["daily", "reader", "bookmarks", "library", "dictionary", "settings", "article", "book", "more"]
LABELS = {
    "daily": ("本日ノニュース", "今日の記事を、読みやすく。"),
    "reader": ("閲読室", "リンクから、読む時間へ。"),
    "bookmarks": ("收藏", "また会いたい記事を残す。"),
    "library": ("書架", "物語の続きを、ここから。"),
    "dictionary": ("辞書", "ひとつの言葉を、深く。"),
    "settings": ("設置", "自分に合う読み方に。"),
    "article": ("文章阅读", "原文・译文・朗读をひとつに。"),
    "book": ("书籍阅读", "物語に向き合う、静かな紙面。"),
    "more": ("更多导航", "收藏と設置へ、すぐに。"),
}


class HeadlessRenderer:
    """CDP for an isolated renderer process, never the user's browser session."""
    def __init__(self, socket):
        self.socket = socket
        self.sequence = 0
        self.session = None

    async def call(self, method, params=None, *, browser=False):
        self.sequence += 1
        message = {"id": self.sequence, "method": method, "params": params or {}}
        if self.session and not browser:
            message["sessionId"] = self.session
        await self.socket.send_json(message)
        while True:
            reply = await self.socket.receive_json(timeout=25)
            if reply.get("id") != self.sequence:
                continue
            if "error" in reply:
                raise RuntimeError(f"Renderer {method}: {reply['error']['message']}")
            return reply.get("result", {})

    async def evaluate(self, expression):
        result = await self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in result:
            description = result["exceptionDetails"].get("exception", {}).get("description", result["exceptionDetails"]["text"])
            raise RuntimeError(f"Design script error: {description}")
        return result["result"].get("value")

    async def capture(self, route, width, height):
        await self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": width < 600})
        await self.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        await self.call("Emulation.setScrollbarsHidden", {"hidden": True})
        await self.call("Page.navigate", {"url": (SOURCE / "screen.html").as_uri() + f"?view={route}"})
        for _ in range(100):
            ready = await self.evaluate("document.readyState === 'complete' && !!document.querySelector('#layout-metrics')")
            if ready:
                break
            await asyncio.sleep(.05)
        else:
            raise RuntimeError(f"Design did not load: {route}/{width}")
        metrics = await self.evaluate("(async()=>{await document.fonts.ready; await new Promise(requestAnimationFrame); reportLayout(); return JSON.parse(document.querySelector('#layout-metrics').textContent)})()")
        if metrics["viewport"] != width or metrics["phoneWidth"] != min(width, 430):
            raise AssertionError(f"Wrong viewport: {metrics}")
        if metrics["documentWidth"] > width or metrics["mainScrollWidth"] > metrics["mainWidth"] + 1 or metrics["overflow"]:
            raise AssertionError(f"Layout overflow: {metrics}")
        images_valid = await self.evaluate("[...document.images].every(image => image.complete && image.naturalWidth > 0)")
        assert images_valid, f"Missing image: {route}/{width}"
        target = OUT / f"{route}-{width}.png"
        if route == "more":
            await self.evaluate("document.activeElement.blur()")
        screenshot = await self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        target.write_bytes(base64.b64decode(screenshot["data"]))
        metrics["image"] = target.name
        with Image.open(target) as image:
            metrics["image_size"] = list(image.size)
            assert image.size == (width * 2, height * 2), image.size
        if width == 390:
            checks = {
                "article": "(()=>{document.querySelector('.translation-toggle').click();const hidden=document.querySelector('.translation').hidden;document.querySelector('.bookmark-toggle').click();document.querySelector('.rate-toggle').click();return hidden&&document.querySelector('.bookmark-toggle').getAttribute('aria-pressed')==='true'&&document.querySelector('.rate-toggle').textContent==='1.25×'})()",
                "settings": "(()=>{const d=document.querySelector('details');d.querySelector('summary').click();return d.open})()",
                "dictionary": "(()=>{document.querySelector('#dictionary-query').value='missing';document.querySelector('#dictionary-form').requestSubmit();const hidden=document.querySelector('.word-detail').hidden;document.querySelector('#dictionary-query').value='木漏れ日';document.querySelector('#dictionary-form').requestSubmit();return hidden&&!document.querySelector('.word-detail').hidden})()",
                "more": "(()=>{const opened=!document.querySelector('#drawer').hidden&&document.querySelector('#main').inert;document.querySelector('#close-drawer').click();return opened&&document.querySelector('#drawer').hidden&&!document.querySelector('#main').inert})()",
                "reader": "(()=>{document.querySelector('[data-dialog=import]').click();const d=document.querySelector('#demo-dialog');return d.open&&document.querySelector('#dialog-copy').textContent.includes('未连接')})()"
            }
            if route in checks:
                metrics["interaction_passed"] = await self.evaluate(checks[route])
                assert metrics["interaction_passed"], f"Interaction failed: {route}"
        return metrics

    async def capture_board(self, width):
        height = 1100 if width > 600 else 844
        await self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
        await self.call("Page.navigate", {"url": (SOURCE / "index.html").as_uri()})
        for _ in range(100):
            ready = await self.evaluate("document.readyState === 'complete' && !!document.querySelector('#screen')?.contentDocument?.querySelector('#layout-metrics')")
            if ready:
                break
            await asyncio.sleep(.05)
        else:
            raise RuntimeError("Design board did not load")
        metrics = await self.evaluate("(async()=>{await document.fonts.ready;return {route:'design-board',viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,buttons:document.querySelectorAll('[data-view]').length,images:[...document.images].every(i=>i.complete&&i.naturalWidth>0)}})()")
        assert metrics["viewport"] == width and metrics["documentWidth"] <= width, metrics
        assert metrics["buttons"] == 9 and metrics["images"], metrics
        screenshot = await self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        (OUT / f"design-board-{width}.png").write_bytes(base64.b64decode(screenshot["data"]))
        clicked = await self.evaluate("(()=>{document.querySelector('[data-view=library]').click();document.querySelector('[data-width=\"375\"]').click();return document.querySelector('#screen').getAttribute('src').endsWith('view=library')&&document.querySelector('[data-width=\"375\"]').getAttribute('aria-pressed')==='true'})()")
        assert clicked, f"Design board controls failed: {width}"
        metrics["interaction_passed"] = clicked
        return metrics


async def render_all(quick):
    results = []
    with tempfile.TemporaryDirectory(prefix="fujimi-design-render-") as temporary:
        profile = Path(temporary) / "edge"
        command = [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-background-networking", "--disable-component-update", "--disable-extensions",
                   "--hide-scrollbars", "--allow-file-access-from-files", "--remote-debugging-port=0",
                   "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}", "about:blank"]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            port_file = profile / "DevToolsActivePort"
            for _ in range(100):
                if port_file.exists():
                    break
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("Headless renderer did not start")
            port, websocket_path = port_file.read_text().splitlines()[:2]
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(f"http://127.0.0.1:{port}{websocket_path}", max_msg_size=20 * 1024 * 1024) as socket:
                    renderer = HeadlessRenderer(socket)
                    target = await renderer.call("Target.createTarget", {"url": "about:blank"}, browser=True)
                    attached = await renderer.call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}, browser=True)
                    renderer.session = attached["sessionId"]
                    await renderer.call("Page.enable")
                    try:
                        for width in ([390] if quick else [375, 390, 1440]):
                            routes = ROUTES if width < 600 else ["daily", "library", "settings"]
                            for route in routes:
                                metrics = await renderer.capture(route, width, 844 if width == 390 else 812 if width == 375 else 1000)
                                results.append(metrics)
                                print(json.dumps({"route": route, "viewport": metrics["viewport"], "phone": metrics["phoneWidth"], "overflow": metrics["overflow"], "interaction": metrics.get("interaction_passed")}), flush=True)
                        if not quick:
                            for width in [375, 390, 1440]:
                                metrics = await renderer.capture_board(width)
                                results.append(metrics)
                                print(json.dumps(metrics), flush=True)
                    finally:
                        await renderer.call("Browser.close", browser=True)
        finally:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
    return results


def font(size: int, serif: bool = False):
    return ImageFont.truetype("C:/Windows/Fonts/NotoSerifSC-VF.ttf" if serif else "C:/Windows/Fonts/NotoSansSC-VF.ttf", size)


def make_board(routes: list[str], filename: str, title: str, subtitle: str, columns: int = 3):
    # Screenshot contact sheet; page pixels come directly from the rendered HTML.
    scale = 1.0 if len(routes) == 3 else .9
    phone_w, phone_h = int(390 * scale), int(844 * scale)
    gap, margin = 50, 65
    top, cell_extra, bottom = 214, 89, 110
    rows = (len(routes) + columns - 1) // columns
    w = margin * 2 + columns * phone_w + gap * (columns - 1)
    h = top + rows * (phone_h + cell_extra) + (rows - 1) * 35 + bottom
    canvas = Image.new("RGB", (w, h), "#eaece5")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((margin, 54, margin + 8, 124), fill="#a3372b")
    draw.text((margin + 27, 48), title, font=font(36, True), fill="#292c28")
    draw.text((margin + 27, 113), subtitle, font=font(15), fill="#6f756a")
    draw.text((w - margin - 166, 61), "富士見新聞文庫", font=font(18, True), fill="#292c28")
    draw.text((w - margin - 166, 100), "手机端设计 / 2026.11", font=font(12), fill="#6f756a")
    draw.line((margin, 167, w - margin, 167), fill="#c9cec1", width=1)
    for index, route in enumerate(routes):
        x = margin + (index % columns) * (phone_w + gap)
        y = top + (index // columns) * (phone_h + cell_extra + 35)
        with Image.open(OUT / f"{route}-390.png") as screenshot:
            screenshot = screenshot.convert("RGB")
            screenshot = screenshot.resize((phone_w, phone_h), Image.Resampling.LANCZOS)
            mask = Image.new("L", (phone_w, phone_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, phone_w - 1, phone_h - 1), radius=18, fill=255)
            draw.rounded_rectangle((x - 1, y - 1, x + phone_w, y + phone_h), radius=19, fill="#c3c8bc")
            canvas.paste(screenshot, (x, y), mask)
        label, description = LABELS[route]
        draw.text((x, y + phone_h + 20), label, font=font(20, True), fill="#292c28")
        draw.text((x, y + phone_h + 57), description, font=font(12), fill="#70766a")
    draw.line((margin, h - 74, w - margin, h - 74), fill="#c9cec1", width=1)
    draw.text((margin, h - 54), "日式书刊 / 墨色 × 朱印 × 留白", font=font(13), fill="#55604f")
    draw.text((w - margin - 398, h - 54), "独立视觉提案 · 内容为合成示意 · 未接入正式服务", font=font(12), fill="#70766a")
    canvas.save(OUT / filename)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--boards-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    if not args.boards_only:
        results = asyncio.run(render_all(args.quick))
        (OUT / "layout-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    make_board(["daily", "article", "library"], "design-preview.png", "日々、読む。", "把新闻、阅读与书架，放回一张安静的纸面。")
    make_board(ROUTES, "all-screens.png", "富士見新聞文庫 / 手机端设计稿", "六个主页面 + 文章阅读 + 书籍阅读 + 更多导航")
    print(json.dumps({"output": str(OUT), "checked": len(results)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
