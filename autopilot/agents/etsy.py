"""Etsy Publisher: creates a digital-download listing per variant, uploads images and the product file,
and (when [etsy] publish = true) makes it live. Also exposes the helpers other agents need (auth, receipts).

Required secrets: ETSY_API_KEY (keystring), ETSY_SHARED_SECRET, ETSY_REFRESH_TOKEN, ETSY_SHOP_ID.
Run `python -m autopilot etsy-auth` once to get the refresh token and shop id.
"""
from .. import http
from ..core import Result, load_copy, persist_secret
from . import factory

API = "https://api.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
SCOPES = "listings_r listings_w transactions_r shops_r"
REQUIRED = ("ETSY_API_KEY", "ETSY_SHARED_SECRET", "ETSY_REFRESH_TOKEN", "ETSY_SHOP_ID")


def missing(ctx):
    return [k for k in REQUIRED if not ctx.env(k)]


def api_key(ctx):
    # Since Jan 2026 Etsy requires "keystring:shared_secret" in x-api-key.
    return f"{ctx.env('ETSY_API_KEY')}:{ctx.env('ETSY_SHARED_SECRET')}"


def access_token(ctx):
    """Exchange the refresh token for a 1-hour access token (once per run) and persist any rotated refresh token."""
    if "etsy_token" in ctx.cache:
        return ctx.cache["etsy_token"]
    # Token refresh is a read-only call in effect, so it is sent even in dry runs.
    import requests
    resp = requests.post(TOKEN_URL, data={"grant_type": "refresh_token", "client_id": ctx.env("ETSY_API_KEY"),
                                          "refresh_token": ctx.env("ETSY_REFRESH_TOKEN")}, timeout=http.TIMEOUT)
    if resp.status_code >= 400:
        raise http.HttpError("POST", TOKEN_URL, resp.status_code, resp.text)
    tok = resp.json()
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != ctx.env("ETSY_REFRESH_TOKEN"):
        if not persist_secret(ctx, "ETSY_REFRESH_TOKEN", new_refresh):
            ctx.log("  ! Etsy issued a new refresh token but it could not be saved (set GH_PAT on GitHub, or use a "
                    ".env file locally). Re-run etsy-auth within 90 days.")
    ctx.cache["etsy_token"] = tok["access_token"]
    return tok["access_token"]


def headers(ctx):
    return {"x-api-key": api_key(ctx), "Authorization": f"Bearer {access_token(ctx)}"}


def call(ctx, method, path, **kw):
    return http.request(ctx, method, f"{API}{path}", headers=headers(ctx), **kw)


def receipts(ctx, min_created):
    """Paid receipts created since the unix timestamp `min_created`."""
    shop, out, offset = ctx.env("ETSY_SHOP_ID"), [], 0
    while True:
        page = call(ctx, "GET", f"/shops/{shop}/receipts",
                    params={"min_created": int(min_created), "limit": 100, "offset": offset, "was_paid": "true"})
        results = page.get("results", [])
        out.extend(results)
        if len(results) < 100:
            return out
        offset += 100


def _publish_variant(ctx, v, copy, cfg):
    shop = ctx.env("ETSY_SHOP_ID")
    vs = ctx.vstate(v.id)
    changed = False
    if not vs.get("etsy_listing_id"):
        listing = call(ctx, "POST", f"/shops/{shop}/listings", data={
            "quantity": cfg.get("quantity", 999),
            "title": copy["etsy_title"],
            "description": copy["description"],
            "price": f"{v.price:.2f}",
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": cfg["taxonomy_id"],
            "type": "download",
            "is_supply": "false",
            "should_auto_renew": "true" if cfg.get("auto_renew", True) else "false",
            "tags": ",".join(copy["tags"]),
        })
        if ctx.dry_run:
            return "would create listing"
        vs["etsy_listing_id"] = listing["listing_id"]
        vs["etsy_url"] = listing.get("url", f"https://www.etsy.com/listing/{listing['listing_id']}")
        vs["etsy_state"] = "draft"
    lid = vs["etsy_listing_id"]
    if not vs.get("etsy_images"):
        imgs = factory.listing_images(ctx, v)[:10]
        if not imgs:
            raise RuntimeError("no listing images rendered (install LibreOffice + poppler-utils)")
        for rank, img in enumerate(imgs, 1):
            with open(img, "rb") as f:
                call(ctx, "POST", f"/shops/{shop}/listings/{lid}/images", files={"image": f}, data={"rank": rank})
        vs["etsy_images"] = len(imgs)
        changed = True
    if not vs.get("etsy_file"):
        product = factory.paths(ctx, v)["product"]
        with open(product, "rb") as f:
            call(ctx, "POST", f"/shops/{shop}/listings/{lid}/files", files={"file": (product.name, f)},
                 data={"name": product.name, "rank": 1})
        vs["etsy_file"] = True
        changed = True
    if cfg.get("publish") and vs.get("etsy_state") != "active":
        call(ctx, "PATCH", f"/shops/{shop}/listings/{lid}", data={"state": "active"})
        vs["etsy_state"] = "active"
        return "published"
    return "draft ready" if changed else "up to date"


def run(ctx):
    cfg = ctx.config.get("etsy", {})
    if not cfg.get("enabled", True):
        return Result.skipped("disabled in autopilot.toml")
    if missing(ctx):
        return Result.needs_setup(f"set secrets {', '.join(missing(ctx))} (see SETUP.md, step 3)")
    if not cfg.get("taxonomy_id"):
        return Result.needs_setup("set [etsy] taxonomy_id (find it with: python -m autopilot etsy-taxonomy planner)")
    done, errors = [], []
    for v in ctx.variants():
        copy = load_copy(ctx.root, v.id)
        if not copy or not factory.paths(ctx, v)["product"].exists():
            continue
        try:
            outcome = _publish_variant(ctx, v, copy, cfg)
            if outcome != "up to date":
                done.append(f"{v.id}: {outcome}")
        except Exception as e:  # keep going with the other variants; state keeps finished steps
            errors.append(f"{v.id}: {e}")
    if errors:
        return Result("error", "; ".join(done + errors))
    if not done:
        return Result.skipped("all listings up to date")
    msg = "; ".join(done)
    if not cfg.get("publish"):
        msg += ". Listings are drafts: set [etsy] publish = true to go live automatically"
    return Result.ok(msg)
