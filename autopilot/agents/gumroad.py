"""Gumroad Promoter: runs the launch discount automatically. It creates the launch code on every mapped
product and deletes it once the launch window ends. Also exposes sales() for the analyst.

Required secret: GUMROAD_ACCESS_TOKEN. Map products in autopilot.toml under [gumroad.products].
"""
from datetime import date

from .. import http
from ..core import Result

API = "https://api.gumroad.com/v2"


def call(ctx, method, path, **kw):
    params = dict(kw.pop("params", {}) or {}, access_token=ctx.env("GUMROAD_ACCESS_TOKEN"))
    return http.request(ctx, method, f"{API}{path}", params=params, **kw)


def sales(ctx, after):
    """All sales on or after the date string `after` (YYYY-MM-DD)."""
    out, page_key = [], None
    while True:
        params = {"after": after}
        if page_key:
            params["page_key"] = page_key
        page = call(ctx, "GET", "/sales", params=params)
        out.extend(page.get("sales", []))
        page_key = page.get("next_page_key")
        if not page_key:
            return out


def run(ctx):
    cfg = ctx.config.get("gumroad", {})
    if not ctx.env("GUMROAD_ACCESS_TOKEN"):
        return Result.needs_setup("set secret GUMROAD_ACCESS_TOKEN (see SETUP.md, step 2)")
    products = {k: v for k, v in cfg.get("products", {}).items() if v}
    if not products:
        return Result.needs_setup("add your Gumroad product id(s) under [gumroad.products] in autopilot.toml")
    code = cfg.get("launch_code", "LAUNCH")
    until = cfg.get("launch_until")
    active = bool(until) and ctx.today <= date.fromisoformat(str(until))
    actions = []
    for variant_id, product_id in products.items():
        existing = call(ctx, "GET", f"/products/{product_id}/offer_codes").get("offer_codes", [])
        match = next((o for o in existing if o.get("name", "").upper() == code.upper()), None)
        if active and not match:
            call(ctx, "POST", f"/products/{product_id}/offer_codes", data={
                "name": code, "offer_type": "percent", "amount_off": cfg.get("launch_percent_off", 40)})
            actions.append(f"created {code} on {variant_id}")
        elif not active and match:
            call(ctx, "DELETE", f"/products/{product_id}/offer_codes/{match['id']}")
            actions.append(f"ended {code} on {variant_id}")
    if not actions:
        state = f"running until {until}" if active else "not running"
        return Result.skipped(f"launch code {code} {state}; nothing to change")
    return Result.ok("; ".join(actions))
