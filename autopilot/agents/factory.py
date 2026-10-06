"""Product Factory: builds every catalog variant (product file, screenshots, cover image).

Only rebuilds a variant when its settings or the builder script change.
"""
import hashlib
import json
import sys

from .. import images
from ..core import ROOT, Result

sys.path.insert(0, str(ROOT / "scripts"))
import build_planner  # noqa: E402

BUILDER_SRC = ROOT / "scripts" / "build_planner.py"


def fingerprint(v):
    h = hashlib.sha256(BUILDER_SRC.read_bytes())
    h.update(json.dumps(v.as_dict(), sort_keys=True).encode())
    h.update(images.Path(images.__file__).read_bytes())
    return h.hexdigest()[:16]


def paths(ctx, v):
    d = ctx.dist / v.id
    return {
        "dir": d,
        "product": d / f"{v.year}-Budget-Finance-Planner.xlsx",
        "demo": d / "demo.xlsx",
        "images": d / "images",
        "cover": d / "images" / "0-cover.jpg",
        "stamp": d / ".fingerprint",
    }


def listing_images(ctx, v):
    p = paths(ctx, v)
    shots = sorted(p["images"].glob("[1-9]-*.png"))
    return ([p["cover"]] if p["cover"].exists() else []) + shots


def run(ctx):
    variants = ctx.variants()
    if not variants:
        return Result.needs_setup("no [[variants]] in autopilot.toml")
    render = images.have_renderer()
    built = []
    for v in variants:
        p = paths(ctx, v)
        fp = fingerprint(v) + ("" if render else "-noimg")
        if p["stamp"].exists() and p["stamp"].read_text() == fp and p["product"].exists():
            continue
        p["dir"].mkdir(parents=True, exist_ok=True)
        build_planner.build(str(p["product"]), v.year, v.currency, v.theme)
        if render:
            build_planner.build(str(p["demo"]), v.year, v.currency, v.theme, demo=True)
            for old in p["images"].glob("*"):
                old.unlink()
            shots = images.screenshots(p["demo"], p["images"])
            t = build_planner.THEMES[v.theme]
            images.cover(shots[0], p["cover"], title=f"{v.year} Budget Planner",
                         subtitle="Excel + Google Sheets  •  7 tabs  •  auto dashboard",
                         primary=t["primary"], cream=t["cream"], accent=t["accent"])
            p["demo"].unlink()
        p["stamp"].write_text(fp)
        built.append(v.id)
        ctx.log(f"  built {v.id}")
    note = "" if render else " (LibreOffice/pdftoppm missing: no images rendered)"
    if not built:
        return Result.skipped(f"all {len(variants)} variants up to date{note}")
    return Result.ok(f"built {len(built)} variant(s): {', '.join(built)}{note}")
