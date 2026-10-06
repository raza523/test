"""Sales Analyst: pulls new orders from Gumroad and Etsy into reports/sales.csv and writes a daily report."""
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..core import Result
from . import etsy, gumroad

FIELDS = ["date", "channel", "order_id", "product", "amount", "currency"]


def _csv(ctx):
    return ctx.reports / "sales.csv"


def read_sales(ctx):
    path = _csv(ctx)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _gumroad_rows(ctx, since):
    rows = []
    for s in gumroad.sales(ctx, since.isoformat()):
        rows.append({"date": str(s.get("created_at", ""))[:10], "channel": "gumroad", "order_id": f"g-{s['id']}",
                     "product": s.get("product_name", ""), "amount": f"{int(s.get('price', 0)) / 100:.2f}",
                     "currency": (s.get("currency") or "usd").upper()})
    return rows


def _etsy_rows(ctx, since):
    rows = []
    start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    for r in etsy.receipts(ctx, start):
        total = r.get("grandtotal") or r.get("total_price") or {}
        amount = total.get("amount", 0) / (total.get("divisor") or 100)
        titles = ", ".join(t.get("title", "") for t in r.get("transactions", []))[:120]
        rows.append({"date": datetime.fromtimestamp(r.get("create_timestamp", 0), timezone.utc).date().isoformat(),
                     "channel": "etsy", "order_id": f"e-{r['receipt_id']}", "product": titles,
                     "amount": f"{amount:.2f}", "currency": total.get("currency_code", "USD")})
    return rows


def summarize(rows, today):
    def window(days):
        start = (today - timedelta(days=days - 1)).isoformat()
        sel = [r for r in rows if r["date"] >= start]
        money = defaultdict(float)
        for r in sel:
            money[r["currency"]] += float(r["amount"])
        return len(sel), ", ".join(f"{v:,.2f} {k}" for k, v in sorted(money.items())) or "0"
    by_product = defaultdict(int)
    for r in rows:
        by_product[(r["channel"], r["product"])] += 1
    return {"today": window(1), "7d": window(7), "30d": window(30), "all": window(100000),
            "top": sorted(by_product.items(), key=lambda kv: -kv[1])[:5]}


def run(ctx):
    sources = []
    if ctx.env("GUMROAD_ACCESS_TOKEN"):
        sources.append(("gumroad", _gumroad_rows))
    if not etsy.missing(ctx):
        sources.append(("etsy", _etsy_rows))
    if not sources:
        return Result.needs_setup("connect Gumroad and/or Etsy to track sales")
    st = ctx.state.setdefault("sales", {})
    seen = set(r["order_id"] for r in read_sales(ctx))
    since = ctx.today - timedelta(days=int(ctx.config.get("sales", {}).get("lookback_days", 7)))
    new, problems = [], []
    for name, fetch in sources:
        try:
            new += [r for r in fetch(ctx, since) if r["order_id"] not in seen]
        except Exception as e:
            problems.append(f"{name}: {e}")
    if new and not ctx.dry_run:
        path = _csv(ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if fresh:
                w.writeheader()
            w.writerows(sorted(new, key=lambda r: r["date"]))
    rows = read_sales(ctx) + ([] if not ctx.dry_run else new)
    s = summarize(rows, ctx.today)
    st["last_summary"] = {k: s[k] for k in ("today", "7d", "30d", "all")}
    lines = [f"# Sales report: {ctx.today.isoformat()}", "",
             "| Window | Orders | Revenue (before fees) |", "|---|---|---|"]
    for label, key in (("Today", "today"), ("Last 7 days", "7d"), ("Last 30 days", "30d"), ("All time", "all")):
        lines.append(f"| {label} | {s[key][0]} | {s[key][1]} |")
    lines += ["", "## Best sellers", ""] + [f"- {n} × {p} ({c})" for (c, p), n in s["top"]] + \
             (["- no sales yet"] if not s["top"] else [])
    if problems:
        lines += ["", "## Problems", ""] + [f"- {p}" for p in problems]
    if not ctx.dry_run:
        out = ctx.reports / "daily" / f"{ctx.today.isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n")
    msg = f"{len(new)} new order(s); last 7 days: {s['7d'][0]} orders, {s['7d'][1]}"
    return Result("error", msg + "; " + "; ".join(problems)) if problems else Result.ok(msg)
