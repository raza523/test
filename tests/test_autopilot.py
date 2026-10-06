import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from autopilot import __main__ as cli
from autopilot import core, http
from autopilot.agents import copywriter, etsy, factory, gumroad, pinterest, sales, social, strategist

REPO = Path(__file__).resolve().parent.parent


class FakeHttp:
    """Records requests and answers them from a list of (method, url-regex, response-or-callable) routes."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, ctx, method, url, **kw):
        if ctx.dry_run and method != "GET":
            return {"dry_run": True}
        self.calls.append((method, url, kw))
        for m, pattern, resp in self.routes:
            if m == method and re.search(pattern, url):
                return resp(kw) if callable(resp) else resp
        raise AssertionError(f"unexpected {method} {url}")

    def count(self, method, pattern):
        return sum(1 for m, u, _ in self.calls if m == method and re.search(pattern, u))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    shutil.copy(REPO / "autopilot.toml", tmp_path / "autopilot.toml")
    for k in list(__import__("os").environ):
        if k.startswith(("ETSY_", "GUMROAD_", "PINTEREST_", "ANTHROPIC_", "GH_PAT")):
            monkeypatch.delenv(k)
    c = core.Ctx(root=tmp_path, config=core.load_config(tmp_path), state={}, today=date(2026, 10, 7))
    c.config["variants"] = c.config["variants"][:2]
    return c


def fake_build(ctx):
    """Stand-in for the factory: product file + images, without LibreOffice."""
    for v in ctx.variants():
        p = factory.paths(ctx, v)
        p["images"].mkdir(parents=True, exist_ok=True)
        p["product"].write_bytes(b"xlsx")
        from PIL import Image
        Image.new("RGB", (400, 260), "white").save(p["images"] / "1-dashboard.png")
        Image.new("RGB", (400, 300), "white").save(p["cover"])


def set_etsy(monkeypatch, ctx, **cfg):
    for k in etsy.REQUIRED:
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("ETSY_SHOP_ID", "77")
    ctx.cache["etsy_token"] = "tok"
    ctx.config["etsy"].update({"taxonomy_id": 1234, **cfg})


def test_copywriter_template_copy_is_marketplace_valid(ctx):
    res = copywriter.run(ctx)
    assert res.status == "ok"
    for v in ctx.variants():
        c = core.load_copy(ctx.root, v.id)
        assert len(c["tags"]) == 13 and all(len(t) <= 20 for t in c["tags"])
        assert len(c["etsy_title"]) <= 140
        assert "AI tools" in c["description"]
        assert len(c["pins"]) >= 3 and c["source"] == "template"
    assert copywriter.run(ctx).status == "skipped"  # never overwrites existing copy


def test_copywriter_upgrades_unedited_template_copy_only(ctx, monkeypatch):
    copywriter.run(ctx)
    first, second = ctx.variants()
    edited = core.load_copy(ctx.root, second.id)
    edited["title"] = "My own title"
    core.copy_path(ctx.root, second.id).write_text(json.dumps(edited))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(copywriter, "_ask_claude", lambda v, b: copywriter._fallback(v, b) | {"title": "AI title"})
    copywriter.run(ctx)
    assert core.load_copy(ctx.root, first.id)["source"] == "claude"
    assert core.load_copy(ctx.root, second.id)["title"] == "My own title"  # hand edits are kept
    assert copywriter.run(ctx).status == "skipped"


def test_copywriter_falls_back_when_claude_fails(ctx, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(copywriter, "_ask_claude", lambda v, b: (_ for _ in ()).throw(RuntimeError("boom")))
    res = copywriter.run(ctx)
    assert res.status == "ok" and "Claude failed" in res.summary


def test_etsy_creates_drafts_once_then_publishes(ctx, monkeypatch):
    fake_build(ctx)
    copywriter.run(ctx)
    set_etsy(monkeypatch, ctx)
    ids = iter([101, 102])
    fake = FakeHttp([
        ("POST", r"/shops/77/listings$", lambda kw: {"listing_id": next(ids)}),
        ("POST", r"/images$", {}), ("POST", r"/files$", {}), ("PATCH", r"/listings/\d+$", {}),
    ])
    monkeypatch.setattr(http, "request", fake)

    res = etsy.run(ctx)
    assert res.status == "ok" and "drafts" in res.summary
    assert fake.count("POST", r"listings$") == 2 and fake.count("POST", r"/files$") == 2
    create = next(kw for m, u, kw in fake.calls if u.endswith("/listings"))
    assert create["data"]["type"] == "download" and create["data"]["price"] == "11.99"
    assert fake.count("PATCH", r".") == 0

    assert etsy.run(ctx).status == "skipped"  # idempotent: nothing re-created
    assert fake.count("POST", r"listings$") == 2

    ctx.config["etsy"]["publish"] = True
    assert etsy.run(ctx).status == "ok"
    assert fake.count("PATCH", r".") == 2
    assert all(s["etsy_state"] == "active" for s in ctx.state["variants"].values())


def test_etsy_resumes_after_partial_failure(ctx, monkeypatch):
    fake_build(ctx)
    copywriter.run(ctx)
    set_etsy(monkeypatch, ctx)
    ctx.config["variants"] = ctx.config["variants"][:1]
    fail = {"left": 1}

    def image(kw):
        if fail["left"]:
            fail["left"] -= 1
            raise http.HttpError("POST", "img", 500, "oops")
        return {}
    fake = FakeHttp([("POST", r"listings$", {"listing_id": 5}), ("POST", r"/images$", image), ("POST", r"/files$", {})])
    monkeypatch.setattr(http, "request", fake)
    assert etsy.run(ctx).status == "error"
    assert etsy.run(ctx).status == "ok"
    assert fake.count("POST", r"listings$") == 1  # listing not duplicated on retry


def test_etsy_needs_setup_without_secrets_or_category(ctx, monkeypatch):
    assert etsy.run(ctx).status == "needs_setup"
    for k in etsy.REQUIRED:
        monkeypatch.setenv(k, "x")
    res = etsy.run(ctx)
    assert res.status == "needs_setup" and "taxonomy_id" in res.summary


def test_gumroad_starts_and_ends_launch_code(ctx, monkeypatch):
    monkeypatch.setenv("GUMROAD_ACCESS_TOKEN", "t")
    ctx.config["gumroad"]["products"] = {"budget-2027-usd-sage": "P1"}
    codes = []
    fake = FakeHttp([
        ("GET", r"/products/P1/offer_codes$", lambda kw: {"offer_codes": list(codes)}),
        ("POST", r"/products/P1/offer_codes$", lambda kw: codes.append({"id": "c1", "name": kw["data"]["name"]}) or {}),
        ("DELETE", r"/offer_codes/c1$", lambda kw: codes.clear() or {}),
    ])
    monkeypatch.setattr(http, "request", fake)
    assert gumroad.run(ctx).status == "ok" and codes and codes[0]["name"] == "LAUNCH"
    assert gumroad.run(ctx).status == "skipped"
    ctx.today = date(2026, 10, 10)  # after launch_until
    assert gumroad.run(ctx).status == "ok" and not codes


def test_sales_dedupes_and_reports(ctx, monkeypatch):
    monkeypatch.setenv("GUMROAD_ACCESS_TOKEN", "t")
    set_etsy(monkeypatch, ctx)
    fake = FakeHttp([
        ("GET", r"gumroad.com/v2/sales$", {"sales": [{"id": "s1", "created_at": "2026-10-07T10:00:00Z",
                                                      "product_name": "2027 Budget", "price": 1199}]}),
        ("GET", r"/shops/77/receipts$", {"results": [{"receipt_id": 9, "create_timestamp": 1791370000,
                                                       "grandtotal": {"amount": 999, "divisor": 100, "currency_code": "GBP"},
                                                       "transactions": [{"title": "2027 Budget Planner"}]}]}),
    ])
    monkeypatch.setattr(http, "request", fake)
    res = sales.run(ctx)
    assert res.status == "ok" and res.summary.startswith("2 new")
    assert sales.run(ctx).summary.startswith("0 new")
    rows = sales.read_sales(ctx)
    assert {r["amount"] for r in rows} == {"11.99", "9.99"}
    assert (ctx.reports / "daily" / "2026-10-07.md").exists()


def test_pinterest_posts_daily_quota_and_rotates(ctx, monkeypatch):
    fake_build(ctx)
    copywriter.run(ctx)
    ctx.config["store"]["gumroad_url"] = "https://me.gumroad.com/l/x"
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "t")
    monkeypatch.setenv("PINTEREST_BOARD_ID", "B")
    fake = FakeHttp([("POST", r"pinterest.com/v5/pins$", {"id": "pin1"})])
    monkeypatch.setattr(http, "request", fake)
    assert pinterest.run(ctx).status == "ok"
    assert fake.count("POST", "pins") == 3
    body = fake.calls[0][2]["json"]
    assert body["link"] == "https://me.gumroad.com/l/x" and body["media_source"]["source_type"] == "image_base64"
    assert pinterest.run(ctx).status == "skipped"  # once per day
    ctx.today = date(2026, 10, 8)
    pinterest.run(ctx)
    keys = [(p["variant"], p["pin"]) for p in ctx.state["pinterest"]["posted"]]
    assert len(keys) == len(set(keys)) == 6  # no repeats until the rotation wraps


def test_social_queue_fills_link(ctx):
    copywriter.run(ctx)
    assert social.run(ctx).status == "needs_setup"
    ctx.config["store"]["gumroad_url"] = "https://me.gumroad.com/l/x"
    assert social.run(ctx).status == "ok"
    text = (ctx.reports / "todo" / "2026-10-07.md").read_text()
    assert "{link}" not in text


def test_strategist_auto_expand_adds_variants_within_cap(ctx):
    ctx.config["strategist"].update({"auto_expand": True, "max_variants": 3})
    assert strategist.run(ctx).status == "ok"
    assert len(ctx.variants()) == 3
    assert strategist.run(ctx).status == "skipped"  # weekly


def test_pipeline_isolates_failures_and_saves_state(ctx, monkeypatch):
    monkeypatch.setattr(factory, "run", lambda c: (_ for _ in ()).throw(RuntimeError("disk full")))
    results = cli.run_pipeline(ctx)
    status = {k: r.status for k, _, r in results}
    assert status["factory"] == "error" and status["copywriter"] == "ok"
    assert (ctx.root / "state" / "state.json").exists()
    assert "disk full" in (ctx.reports / "STATUS.md").read_text()


def test_dry_run_writes_nothing(ctx):
    ctx.dry_run = True
    cli.run_pipeline(ctx, {"copywriter", "strategist"})
    assert not (ctx.root / "state").exists() and not (ctx.root / "reports").exists()


def test_factory_builds_variant_files(ctx, monkeypatch):
    monkeypatch.setattr(factory.images, "have_renderer", lambda: False)
    ctx.config["variants"] = [{"year": 2028, "currency": "€", "theme": "midnight", "price": 9.5}]
    res = factory.run(ctx)
    assert res.status == "ok"
    from openpyxl import load_workbook
    wb = load_workbook(factory.paths(ctx, ctx.variants()[0])["product"])
    assert "€" in wb["Dashboard"]["C8"].number_format and wb["Dashboard"]["B1"].value == "2028 Dashboard"
    assert factory.run(ctx).status == "skipped"  # fingerprint unchanged
