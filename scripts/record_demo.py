"""Record the README demo GIFs from the live app, as described by a spec such as assets/demo/olm-session.toml.

Usage:
  python scripts/record_demo.py run <spec.toml> --scheme light|dark [--font PATH] [--frames DIR]
  python scripts/record_demo.py gif <spec.toml> --scheme light|dark --frames DIR [--font PATH]

`run` starts `groundcast serve` on a free port with an empty, temporary data directory, then drives the
page in Chrome: fetch the spec's web page, fill in its brief, and start the session (part 1); it waits
for the session to finish, which calls the configured LLM backend for real, then plays it and opens the
source of the sentence being read (part 2). It stops the service and writes the GIF named in the spec's
[output] table next to the spec. `gif` composes the GIF again from frames a `run --frames DIR` kept, for
example to try another speed.

Chrome's screencast saves lossless frames with their timestamps; a drawn cursor stands in for the mouse,
which headless Chrome does not paint, and the source page opens in the same tab. The card between the
two parts is set in --font (the Fraunces variable font, from https://github.com/undercasetype/Fraunces),
else in a serif system font. Needs `pip install playwright pillow` (only for this script), Google Chrome,
and resvg-py (the dev extra).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

import resvg_py
from PIL import Image
from playwright.sync_api import Page, sync_playwright

PARTS = ("1", "2")
INDEX = "frames.txt"  # timestamp and file per line; MARK ends a screencast
CARD = {  # background, title, line, rule: the app's own colours
    "light": ("#f4f1ea", "#0e3b3a", "#5b6d6a", "#d98a1e"),
    "dark": ("#0d1012", "#fff4e0", "#a9b8b4", "#f0a23b"),
}

CURSOR_JS = """
(() => {
  const add = () => {
    if (document.getElementById('demo-cursor')) return;
    const c = document.createElement('div');
    c.id = 'demo-cursor';
    c.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M3 2l0 22 6-5.5 4.2 9.3 3.8-1.7-4.1-9.2 8.3-0.4z" fill="#111" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none',
      filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.35))'});
    const r = document.createElement('div');
    Object.assign(r.style, {position: 'fixed', left: '0', top: '0', width: '36px', height: '36px', borderRadius: '50%',
      background: 'rgba(240,162,59,.45)', zIndex: 2147483646, pointerEvents: 'none', opacity: '0'});
    document.documentElement.append(c, r);
    const at = (x, y) => { c.style.transform = `translate(${x - 3}px, ${y - 2}px)`; };
    at(...(window.__demoPos || [innerWidth / 2, innerHeight / 2]));
    addEventListener('mousemove', e => { window.__demoPos = [e.clientX, e.clientY]; at(e.clientX, e.clientY); }, true);
    addEventListener('mousedown', e => {
      const t = (s) => `translate(${e.clientX - 18}px, ${e.clientY - 18}px) scale(${s})`;
      r.style.transition = 'none'; r.style.opacity = '1'; r.style.transform = t(.4);
      requestAnimationFrame(() => { r.style.transition = 'opacity .45s, transform .45s';
        r.style.opacity = '0'; r.style.transform = t(1.4); });
    }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', add); else add();
})();
"""


class Recorder:
    """Moves a visible cursor and keeps the screencast frames of one page."""

    def __init__(self, page: Page, out: Path) -> None:
        self.page, self.out = page, out
        out.mkdir(parents=True, exist_ok=True)
        self.index = (out / INDEX).open("a", encoding="ascii")
        self.n = len(list(out.glob("f*.png")))
        size = page.viewport_size
        self.size = (size["width"], size["height"])
        self.pos = (self.size[0] / 2, self.size[1] / 2)
        self.cdp = None

    def start(self) -> None:
        self.cdp = self.page.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.cdp.send("Page.startScreencast", {"format": "png", "maxWidth": self.size[0], "maxHeight": self.size[1]})

    def stop(self) -> None:
        self.hold(0.3)
        self.cdp.send("Page.stopScreencast")
        self.cdp.detach()
        self.index.write("MARK\n")
        self.index.flush()

    def _frame(self, event: dict) -> None:
        name = f"f{self.n:05d}.png"
        (self.out / name).write_bytes(base64.b64decode(event["data"]))
        self.index.write(f"{event['metadata']['timestamp']:.4f} {name}\n")
        self.n += 1
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:  # the screencast was stopped while this frame was on its way
            pass

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def move(self, x: float, y: float, seconds: float = 0.6) -> None:
        steps = max(8, int(seconds * 40))
        x0, y0 = self.pos
        for i in range(1, steps + 1):
            e = (i / steps) ** 2 * (3 - 2 * i / steps)  # smoothstep
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(int(seconds * 1000 / steps))
        self.pos = (x, y)

    def to(self, selector: str, seconds: float = 0.6, dx: float = 0.5) -> None:
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        self.move(box["x"] + box["width"] * dx, box["y"] + box["height"] / 2, seconds)

    def press(self) -> None:
        self.page.mouse.down()
        self.page.wait_for_timeout(70)
        self.page.mouse.up()

    def click(self, selector: str, seconds: float = 0.6) -> None:
        self.to(selector, seconds)
        self.hold(0.15)
        self.press()
        self.hold(0.25)


def record_part1(pg: Page, r: Recorder, spec: dict) -> None:
    brief = spec["brief"]
    r.start()
    r.hold(1.2)
    r.click("#url-input", 0.9)
    pg.keyboard.type(spec["material"]["url"], delay=38)
    r.hold(0.4)
    r.click("#url-form button[type=submit]", 0.5)
    pg.wait_for_function("document.querySelectorAll('#materials li').length > 0", timeout=120_000)
    r.hold(0.6)
    r.to("#materials li", 0.7)
    r.hold(1.6)
    r.click("nav >> text=New session", 0.8)
    r.hold(0.8)
    r.click("#tab-form", 0.7)
    r.hold(0.3)
    r.click("#focus", 0.5)
    pg.keyboard.type(brief["focus"], delay=14)
    r.hold(0.3)
    lo, hi, now = (float(pg.get_attribute("#minutes", a)) for a in ("min", "max", "value"))
    slider = pg.locator("#minutes").bounding_box()
    r.to("#minutes", 0.5, dx=(now - lo) / (hi - lo))
    pg.mouse.down()
    r.move(slider["x"] + slider["width"] * (brief["minutes"] - lo) / (hi - lo), r.pos[1], 0.5)
    pg.mouse.up()
    for _ in range(int(hi - lo)):  # the thumb's own width puts a drag a step off; the keys settle it
        value = int(pg.eval_on_selector("#minutes", "m => m.value"))
        if value == brief["minutes"]:
            break
        pg.keyboard.press("ArrowRight" if value < brief["minutes"] else "ArrowLeft")
        r.hold(0.12)
    for group, key in (("#context-group", "listen"), ("#format-group", "format"), ("#level-group", "level")):
        r.hold(0.3)
        r.click(f"{group} >> text={brief[key]}", 0.6)
    r.hold(0.3)
    r.click("#brief-form button[type=submit]", 0.8)
    r.hold(0.6)
    r.to("#brief-summary", 0.6)
    r.hold(1.6)
    r.click("#brief-confirm", 0.7)
    r.hold(4.5)
    r.stop()


def record_part2(pg: Page, r: Recorder) -> None:
    pg.click("nav >> text=Sessions")
    pg.wait_for_timeout(600)
    pg.click("#sessions li >> nth=0")
    pg.wait_for_timeout(1500)
    pg.evaluate("scrollTo(0, 0)")
    box = pg.locator("#sessions li").first.bounding_box()
    r.pos = (box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
    pg.mouse.move(*r.pos)
    r.start()
    r.hold(1.0)
    r.click(".big-play", 0.8)
    r.hold(1.2)
    r.to(".verify-card .score", 0.8)
    r.hold(1.8)
    for _ in range(30):
        pg.mouse.wheel(0, 560 / 30)
        pg.wait_for_timeout(33)
    r.hold(0.6)
    # Open the source of the sentence being read; follow-along scrolling can move it while the cursor travels.
    pg.wait_for_function("document.querySelector('.reader .sent.now .cite a')", timeout=60_000)
    pg.evaluate("document.querySelectorAll('.reader .cite a').forEach(a => a.removeAttribute('target'))")
    pg.evaluate("document.querySelector('.reader .sent.now .cite a').id = 'demo-cite'")
    cite = pg.locator("#demo-cite")
    sentence = cite.locator("xpath=ancestor::span[contains(@class,'sent')]").bounding_box()
    r.move(sentence["x"] + 40, sentence["y"] + sentence["height"] / 2, 0.8)
    r.hold(0.8)
    for _ in range(3):
        box = cite.bounding_box()
        r.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, 0.5)
    r.hold(0.4)
    box = cite.bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    r.press()
    pg.wait_for_url("**view.html**", timeout=10_000)
    pg.wait_for_load_state()
    pg.wait_for_timeout(400)
    r.stop()
    r.start()  # the source page is a new document
    r.hold(3.2)
    r.stop()


def get_json(url: str, method: str = "GET") -> object:
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=10) as res:
        return json.load(res)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(spec: dict, scheme: str, frames: Path, channel: str) -> float:
    """Record both parts into frames/1 and frames/2; return the minutes the session took to make."""
    rec = spec["recording"]
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="groundcast-demo-") as data:
        env = {**os.environ, "GROUNDCAST_DATA_DIR": data, "GROUNDCAST_SERVER_HOST": "127.0.0.1",
               "GROUNDCAST_SERVER_PORT": str(port)}  # fmt: skip
        log = (frames / "serve.log").open("w", encoding="utf-8")
        server = subprocess.Popen([sys.executable, "-m", "groundcast", "serve"], env=env, stdout=log,
                                  stderr=subprocess.STDOUT)  # fmt: skip
        try:
            for _ in range(120):
                try:
                    get_json(base + "/api/health")
                    break
                except OSError:
                    if server.poll() is not None:
                        raise SystemExit(f"groundcast serve exited; see {frames / 'serve.log'}")
                    time.sleep(1)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel=channel)
                ctx = browser.new_context(viewport={"width": rec["width"], "height": rec["height"]},
                                          device_scale_factor=1, color_scheme=scheme)  # fmt: skip
                ctx.add_init_script(CURSOR_JS)
                pg = ctx.new_page()
                pg.goto(base + "/")
                pg.wait_for_timeout(1500)
                record_part1(pg, Recorder(pg, frames / "1"), spec)
                print("part 1 recorded; waiting for the session")
                deadline = time.monotonic() + rec["session_timeout_min"] * 60
                while True:
                    session = get_json(base + "/api/sessions")[0]
                    if session["status"] not in ("queued", "running"):
                        break
                    if time.monotonic() > deadline:
                        raise SystemExit("the session did not finish in time")
                    time.sleep(10)
                if session["status"] != "done":
                    raise SystemExit(f"the session ended as {session['status']}: {session['error']}")
                pg.goto(base + "/")
                pg.wait_for_timeout(1200)
                record_part2(pg, Recorder(pg, frames / "2"))
                browser.close()
            get_json(base + "/api/shutdown", "POST")
            server.wait(30)
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(30)
            log.close()
    took = datetime.fromisoformat(session["finished_at"]) - datetime.fromisoformat(session["created_at"])
    return took.total_seconds() / 60


def card(spec: dict, scheme: str, font: Path | None, minutes: float, path: Path) -> None:
    rec, text = spec["recording"], spec["card"]
    w, h = rec["width"], rec["height"]
    bg, title, line, rule = CARD[scheme]
    family = "Fraunces" if font else "serif"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="{bg}"/>
<path d="M{w / 2 - 80} {h / 2 + 12}H{w / 2 + 80}" stroke="{rule}" stroke-width="3" stroke-linecap="round"/>
<text x="{w / 2}" y="{h / 2 - 16}" text-anchor="middle" font-family="{family}" font-weight="600" font-size="54" fill="{title}">{text["title"].format(minutes=round(minutes))}</text>
<text x="{w / 2}" y="{h / 2 + 60}" text-anchor="middle" font-family="{family}" font-size="26" fill="{line}">{text["line"]}</text>
</svg>"""
    fonts = {"font_files": [str(font)], "skip_system_fonts": True} if font else {}
    path.write_bytes(resvg_py.svg_to_bytes(svg_string=svg, **fonts))


def screencasts(folder: Path) -> list[list[tuple[float, Path]]]:
    casts, cast = [], []
    for line in (folder / INDEX).read_text(encoding="ascii").splitlines():
        if line == "MARK":
            casts.append(cast)
            cast = []
        else:
            t, name = line.split()
            cast.append((float(t), folder / name))
    return [c for c in casts if c]


def compose(spec: dict, frames: Path, card_png: Path, out: Path) -> None:
    rec = spec["recording"]
    shown = []  # (frame, seconds on screen)
    for part in PARTS:
        for cast in screencasts(frames / part):
            for (t, f), nxt in zip(cast, cast[1:] + [None]):
                gap = nxt[0] - t if nxt else rec["last_hold_s"]
                shown.append((f, min(gap, rec["max_gap_s"]) / rec["speed"]))
        if part == PARTS[0]:
            shown.append((card_png, rec["card_s"]))
    # Resample to a constant frame rate (output frame k shows what is on screen at k / fps), then merge repeats.
    runs, k, t, step = [], 0, 0.0, 1 / rec["fps"]
    for f, seconds in shown:
        t += seconds
        while (k + 0.5) * step < t:
            if runs and runs[-1][0] == f:
                runs[-1][1] += 1
            else:
                runs.append([f, 1])
            k += 1
    size = (rec["width"], rec["height"])
    load = lambda f: Image.open(f).convert("RGB").resize(size, Image.LANCZOS)  # noqa: E731
    sample = [load(runs[i][0]) for i in range(0, len(runs), max(1, len(runs) // 24))]
    sheet = Image.new("RGB", (size[0], size[1] * len(sample)))
    for i, im in enumerate(sample):
        sheet.paste(im, (0, size[1] * i))
    palette = sheet.quantize(colors=rec["colors"], method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    images = [load(f).quantize(palette=palette, dither=Image.Dither.NONE) for f, _ in runs]
    durations, total = [], 0.0
    for _, n in runs:  # whole centiseconds, as GIF stores them, carrying the rounding so the total stays right
        total += n * 100 / rec["fps"]
        durations.append(max(2, round(total) - sum(durations) // 10) * 10)
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=0, disposal=1)
    print(f"wrote {out}: {sum(durations) / 1000:.1f} s, {out.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("run", "gif"))
    ap.add_argument("spec", type=Path)
    ap.add_argument("--scheme", choices=sorted(CARD), required=True)
    ap.add_argument("--font", type=Path, help="Fraunces variable font for the card")
    ap.add_argument("--frames", type=Path, help="keep frames here (run), or read them from here (gif)")
    ap.add_argument("--minutes", type=float, help="gif: the wait to name on the card (run measures it)")
    ap.add_argument("--channel", default="chrome", help="Playwright browser channel")
    a = ap.parse_args()
    spec = tomllib.loads(a.spec.read_text(encoding="utf-8"))
    out = a.spec.parent / spec["output"][a.scheme]
    if a.command == "gif" and not a.frames:
        ap.error("gif needs --frames")
    with tempfile.TemporaryDirectory(prefix="groundcast-frames-") as tmp:
        frames = a.frames or Path(tmp)
        frames.mkdir(parents=True, exist_ok=True)
        if a.command == "run":
            for part in PARTS:
                if (frames / part / INDEX).exists():
                    raise SystemExit(f"{frames / part} already holds frames; give an empty --frames folder")
            minutes = run(spec, a.scheme, frames, a.channel)
            (frames / "minutes.txt").write_text(f"{minutes:.2f}\n", encoding="ascii")
        else:
            saved = frames / "minutes.txt"
            if a.minutes is None and not saved.exists():
                ap.error(f"no {saved}; give --minutes")
            minutes = a.minutes if a.minutes is not None else float(saved.read_text(encoding="ascii"))
        card(spec, a.scheme, a.font, minutes, frames / "card.png")
        compose(spec, frames, frames / "card.png", out)


if __name__ == "__main__":
    main()
