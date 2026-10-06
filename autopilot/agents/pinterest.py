"""Pinterest Marketer: designs and posts a few pins a day, rotating through every variant and angle.

Required secrets: PINTEREST_ACCESS_TOKEN (or PINTEREST_REFRESH_TOKEN + PINTEREST_APP_ID + PINTEREST_APP_SECRET)
and PINTEREST_BOARD_ID. New Pinterest apps start in "trial" access, which can post only to your own account.
"""
import base64
import sys
import tempfile
from pathlib import Path

import requests

from .. import http, images
from ..core import ROOT, Result, load_copy
from . import factory

sys.path.insert(0, str(ROOT / "scripts"))
import build_planner  # noqa: E402

API = "https://api.pinterest.com/v5"


def token(ctx):
    if ctx.env("PINTEREST_REFRESH_TOKEN") and ctx.env("PINTEREST_APP_ID") and ctx.env("PINTEREST_APP_SECRET"):
        resp = requests.post(f"{API}/oauth/token", auth=(ctx.env("PINTEREST_APP_ID"), ctx.env("PINTEREST_APP_SECRET")),
                             data={"grant_type": "refresh_token", "refresh_token": ctx.env("PINTEREST_REFRESH_TOKEN")},
                             timeout=http.TIMEOUT)
        if resp.status_code >= 400:
            raise http.HttpError("POST", f"{API}/oauth/token", resp.status_code, resp.text)
        return resp.json()["access_token"]
    return ctx.env("PINTEREST_ACCESS_TOKEN")


def queue(ctx):
    """Every (variant, pin) pair that has a link and an image to point at, in a stable order."""
    items = []
    for v in ctx.variants():
        copy, link = load_copy(ctx.root, v.id), ctx.store_link(v)
        dash = factory.paths(ctx, v)["images"] / "1-dashboard.png"
        if not copy or not link or not dash.exists():
            continue
        for i, p in enumerate(copy.get("pins", [])):
            items.append((v, i, p, link, dash))
    # Interleave variants so consecutive pins differ: sort by pin index, then variant order.
    return sorted(items, key=lambda t: t[1])


def run(ctx):
    cfg = ctx.config.get("pinterest", {})
    if not cfg.get("enabled", True):
        return Result.skipped("disabled in autopilot.toml")
    if not (ctx.env("PINTEREST_ACCESS_TOKEN") or ctx.env("PINTEREST_REFRESH_TOKEN")) or not ctx.env("PINTEREST_BOARD_ID"):
        return Result.needs_setup("set secrets PINTEREST_ACCESS_TOKEN and PINTEREST_BOARD_ID (see SETUP.md, step 4)")
    st = ctx.state.setdefault("pinterest", {"cursor": 0, "posted": []})
    if st.get("last_day") == ctx.today.isoformat():
        return Result.skipped("already pinned today")
    items = queue(ctx)
    if not items:
        return Result.needs_setup("nothing to pin yet: needs a store link (a live Etsy listing or [store] gumroad_url)")
    per_day = int(cfg.get("pins_per_day", 3))
    bearer = {"Authorization": f"Bearer {token(ctx)}"}
    posted = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(min(per_day, len(items))):
            v, i, p, link, dash = items[(st["cursor"] + n) % len(items)]
            t = build_planner.THEMES[v.theme]
            img = images.pin(dash, Path(tmp) / f"pin-{n}.jpg", headline=p["headline"], footer="Instant download →",
                             primary=t["primary"], cream=t["cream"], accent=t["accent"])
            body = {
                "board_id": ctx.env("PINTEREST_BOARD_ID"),
                "title": p["title"][:100],
                "description": p["description"][:500],
                "link": link,
                "alt_text": f"Screenshot of the {v.year} budget planner spreadsheet dashboard"[:500],
                "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                                 "data": base64.b64encode(Path(img).read_bytes()).decode()},
            }
            res = http.request(ctx, "POST", f"{API}/pins", headers=bearer, json=body)
            posted.append({"date": ctx.today.isoformat(), "variant": v.id, "pin": i, "id": res.get("id")})
    st["cursor"] = (st["cursor"] + len(posted)) % len(items)
    st["posted"] = (st.get("posted", []) + posted)[-500:]
    st["last_day"] = ctx.today.isoformat()
    return Result.ok(f"posted {len(posted)} pin(s); {len(items)} pins in rotation")
