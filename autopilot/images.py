"""Turns workbooks into listing images: tab screenshots, a 4:3 cover and 2:3 Pinterest pins."""
from __future__ import annotations

import glob
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
SERIF_BOLD = FONT_DIR / "DejaVuSerif-Bold.ttf"
SANS = FONT_DIR / "DejaVuSans.ttf"
SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

# Print order of the workbook's tabs; Transactions spans every page not claimed by the others.
SHEET_ORDER = ["how-it-works", "dashboard", "setup", "transactions", "savings-goals", "debt-payoff", "bill-tracker"]
LISTING_ORDER = ["dashboard", "transactions", "savings-goals", "debt-payoff", "bill-tracker", "setup", "how-it-works"]


def have_renderer():
    return bool(shutil.which("soffice") and shutil.which("pdftoppm"))


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _crop_white(im):
    bg = Image.new("RGB", im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).getbbox()
    return im.crop(box) if box else im


def screenshots(xlsx, out_dir, dpi=110):
    """Render each tab of `xlsx` to `out_dir/<n>-<tab>.png` in listing order. Returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # A private LibreOffice profile avoids lock clashes with any other soffice process.
        subprocess.run(["soffice", f"-env:UserInstallation=file://{tmp}/profile", "--headless",
                        "--convert-to", "pdf", "--outdir", str(tmp), str(xlsx)],
                       check=True, capture_output=True, timeout=300)
        pdf = tmp / (Path(xlsx).stem + ".pdf")
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(tmp / "pg")], check=True, timeout=300)
        pages = sorted(glob.glob(str(tmp / "pg-*.png")), key=lambda p: int(p.rsplit("-", 1)[1][:-4]))
        tx_pages = len(pages) - (len(SHEET_ORDER) - 1)
        if tx_pages < 1:
            raise RuntimeError(f"expected at least {len(SHEET_ORDER)} pages, got {len(pages)}")
        by_sheet, i = {}, 0
        for sheet in SHEET_ORDER:
            by_sheet[sheet] = pages[i]
            i += tx_pages if sheet == "transactions" else 1
        paths = []
        for n, sheet in enumerate(LISTING_ORDER, 1):
            dest = out_dir / f"{n}-{sheet}.png"
            _crop_white(Image.open(by_sheet[sheet]).convert("RGB")).save(dest)
            paths.append(dest)
    return paths


def _hex(c):
    return "#" + c[-6:]


def _paste_card(canvas, shot, box_w, top, radius=18):
    """Paste a screenshot scaled to `box_w` wide, centered, with a soft shadow. Returns its bottom y."""
    scale = box_w / shot.width
    shot = shot.resize((box_w, int(shot.height * scale)), Image.LANCZOS)
    x = (canvas.width - shot.width) // 2
    shadow = Image.new("RGBA", (shot.width + 60, shot.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((30, 36, shot.width + 30, shot.height + 36), radius, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.paste(shadow, (x - 30, top - 30), shadow)
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *shot.size), radius, fill=255)
    canvas.paste(shot, (x, top), mask)
    return top + shot.height


def _centered(draw, text, y, font, fill, width):
    w = draw.textlength(text, font=font)
    draw.text(((width - w) / 2, y), text, font=font, fill=fill)


def cover(dashboard_png, out, *, title, subtitle, primary, cream, accent):
    """4:3 marketplace thumbnail: colored band with title, dashboard screenshot below."""
    W, H = 2000, 1500
    im = Image.new("RGB", (W, H), _hex(cream))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 520), fill=_hex(primary))
    _centered(d, title, 110, _font(SERIF_BOLD, 110), "white", W)
    _centered(d, subtitle, 270, _font(SANS, 54), "#F2F2F2", W)
    badge = "INSTANT DOWNLOAD"
    bf = _font(SANS_BOLD, 40)
    bw = d.textlength(badge, font=bf) + 80
    d.rounded_rectangle(((W - bw) / 2, 375, (W + bw) / 2, 455), 40, fill=_hex(accent))
    _centered(d, badge, 393, bf, "white", W)
    _paste_card(im, Image.open(dashboard_png).convert("RGB"), 1700, 590)
    im.save(out, quality=92)
    return out


def pin(dashboard_png, out, *, headline, footer, primary, cream, accent):
    """1000x1500 Pinterest pin: big headline, screenshot, call to action."""
    W, H = 1000, 1500
    im = Image.new("RGB", (W, H), _hex(cream))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 560), fill=_hex(primary))
    hf = _font(SERIF_BOLD, 78)
    lines = textwrap.wrap(headline, width=18)[:4]
    y = 280 - len(lines) * 50
    for line in lines:
        _centered(d, line, y, hf, "white", W)
        y += 100
    bottom = _paste_card(im, Image.open(dashboard_png).convert("RGB"), 900, 640)
    cf = _font(SANS_BOLD, 44)
    cw = d.textlength(footer, font=cf) + 90
    cy = max(bottom + 80, 1260)
    d.rounded_rectangle(((W - cw) / 2, cy, (W + cw) / 2, cy + 100), 50, fill=_hex(accent))
    _centered(d, footer, cy + 24, cf, "white", W)
    im.save(out, quality=90)
    return out
