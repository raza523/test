"""Strategist (weekly): looks at sales and the catalog, recommends what to make next, and, when
[strategist] auto_expand = true, adds the new variants itself so the factory and publishers pick them up.
"""
import json
from datetime import date, timedelta
from typing import List, Literal

from pydantic import BaseModel, Field

from ..core import CURRENCY_CODES, THEMES, Result
from .copywriter import MODEL
from .sales import read_sales, summarize


class NewVariant(BaseModel):
    year: int
    currency: Literal["$", "£", "€"]
    theme: Literal["sage", "blush", "midnight"]
    price: float = Field(description="Price in the variant's currency")
    reason: str


class Plan(BaseModel):
    summary: str = Field(description="3-5 sentence read of how the shop is doing and why")
    new_variants: List[NewVariant] = Field(description="0-3 variants worth adding next")
    actions_for_owner: List[str] = Field(description="Up to 5 concrete things the owner could do this week")


def _candidates(ctx, existing):
    """Rule-based fallback: next-year and other-currency versions of what exists, most promising first."""
    years = [ctx.today.year + 1] if ctx.today.month >= 9 else [ctx.today.year, ctx.today.year + 1]
    out = []
    for y in years:
        for cur in ("$", "£", "€"):
            for theme in THEMES:
                key = f"budget-{y}-{CURRENCY_CODES[cur]}-{theme}"
                if key not in existing:
                    out.append(NewVariant(year=y, currency=cur, theme=theme, price=11.99,
                                          reason="fills a gap in year/currency/theme coverage"))
    return out


def _ask_claude(ctx, catalog, sales_summary, recent):
    import anthropic

    client = anthropic.Anthropic()
    prompt = f"""You are the growth strategist for a small shop selling a budget-planner spreadsheet on Etsy
and Gumroad. Today is {ctx.today.isoformat()}.

Current catalog (year, currency, theme, price):
{json.dumps(catalog, ensure_ascii=False)}

Sales summary: {json.dumps(sales_summary)}
Last 60 days of orders (date, channel, product, amount, currency):
{json.dumps(recent, ensure_ascii=False)}

Variants can only differ by year, currency ($, £, €) and color theme (sage, blush, midnight). Suggest at most 3
new variants that are not already in the catalog, only when they are likely to add sales (think about seasonality:
New Year demand peaks Nov-Jan; which currencies/themes are selling). An empty list is a fine answer. Keep
actions_for_owner practical and honest; don't promise results."""
    resp = client.beta.messages.parse(
        model=MODEL, max_tokens=16000, output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": prompt}], output_format=Plan,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"no usable plan (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def run(ctx):
    cfg = ctx.config.get("strategist", {})
    st = ctx.state.setdefault("strategist", {})
    last = st.get("last_run")
    if last and ctx.today - date.fromisoformat(last) < timedelta(days=int(cfg.get("every_days", 7))):
        return Result.skipped(f"last ran {last}")
    variants = ctx.variants()
    existing = {v.id for v in variants}
    catalog = [v.as_dict() for v in variants]
    rows = read_sales(ctx)
    summary = summarize(rows, ctx.today)
    recent_start = (ctx.today - timedelta(days=60)).isoformat()
    recent = [[r["date"], r["channel"], r["product"], r["amount"], r["currency"]] for r in rows if r["date"] >= recent_start]
    source = "rules"
    if ctx.env("ANTHROPIC_API_KEY"):
        try:
            plan, source = _ask_claude(ctx, catalog, {k: summary[k] for k in ("7d", "30d", "all")}, recent), "claude"
        except Exception as e:
            ctx.log(f"  ! strategist Claude call failed: {e}")
    if source == "rules":
        plan = Plan(summary=f"{summary['30d'][0]} orders in the last 30 days.",
                    new_variants=_candidates(ctx, existing)[:2],
                    actions_for_owner=["Post one short screen-recording video of the dashboard updating.",
                                       "Reply to every comment and message within a day."])
    max_variants = int(cfg.get("max_variants", 12))
    proposals = [nv for nv in plan.new_variants
                 if f"budget-{nv.year}-{CURRENCY_CODES[nv.currency]}-{nv.theme}" not in existing
                 and ctx.today.year <= nv.year <= ctx.today.year + 1 and 3 <= nv.price <= 60]
    added = []
    if cfg.get("auto_expand") and not ctx.dry_run:
        room = max(0, max_variants - len(variants))
        for nv in proposals[:room]:
            ctx.state.setdefault("extra_variants", []).append(
                {"year": nv.year, "currency": nv.currency, "theme": nv.theme, "price": round(nv.price, 2)})
            added.append(f"{nv.year} {nv.currency} {nv.theme}")
    lines = [f"# Weekly strategy: {ctx.today.isoformat()} ({source})", "", plan.summary, "", "## Suggested new variants", ""]
    lines += [f"- {nv.year} / {nv.currency} / {nv.theme} at {nv.currency}{nv.price:.2f}: {nv.reason}" for nv in proposals] or ["- none"]
    lines += ["", "Added automatically: " + (", ".join(added) if added else
              ("none (auto_expand is off)" if not cfg.get("auto_expand") else "none"))]
    lines += ["", "## For you this week", ""] + [f"- {a}" for a in plan.actions_for_owner]
    if not ctx.dry_run:
        out = ctx.reports / "strategy" / f"{ctx.today.isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n")
        st["last_run"] = ctx.today.isoformat()
    return Result.ok(f"{len(proposals)} suggestion(s), {len(added)} added ({source})")
