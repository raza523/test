"""Copywriter: writes listing copy, Etsy tags, Pinterest pins and social posts for each variant.

Uses Claude when ANTHROPIC_API_KEY is set; otherwise falls back to solid built-in templates.
Copy is saved to state/copy/<variant>.json. Edit those files by hand any time; the agent never
overwrites edited copy (delete a file to have it rewritten). Unedited template copy is upgraded to
Claude-written copy once ANTHROPIC_API_KEY is set.
"""
import hashlib
import json
import re
from typing import List, Literal

from pydantic import BaseModel, Field

from ..core import Result, copy_path, load_copy

MODEL = "claude-opus-5-5"
CURRENCY_NAMES = {"$": "US dollars", "£": "British pounds", "€": "euros"}
THEME_NAMES = {"sage": "sage green", "blush": "blush pink", "midnight": "midnight navy"}
TAG_RE = re.compile(r"[^A-Za-z0-9 \-']")


class Pin(BaseModel):
    headline: str = Field(description="4-7 word hook printed on the pin image, max 40 characters")
    title: str = Field(description="Pin title, max 100 characters")
    description: str = Field(description="Pin description with natural keywords, max 450 characters")


class SocialPost(BaseModel):
    platform: Literal["reddit", "facebook_group", "instagram", "tiktok", "x", "linkedin"]
    text: str = Field(description="Ready-to-paste post. Use the literal placeholder {link} where the link goes.")


class ListingCopy(BaseModel):
    title: str = Field(description="Gumroad product title, max 80 characters")
    etsy_title: str = Field(description="Keyword-rich Etsy title, max 140 characters")
    description: str = Field(description="Full sales description, plain text with line breaks and simple bullets")
    tags: List[str] = Field(description="Exactly 13 Etsy search tags, each max 20 characters, letters/numbers/spaces only")
    pins: List[Pin] = Field(description="6 distinct Pinterest pins, each with a different angle")
    social_posts: List[SocialPost] = Field(description="8 posts across the platforms")


FEATURES = """- Dashboard: income vs. expenses chart, spending pie chart, savings rate, running balance, 12-month overview
- Budget vs. actual for 18 renameable categories; overspending turns red automatically
- Transaction log: 1,000 rows, category dropdown, income/expense detected automatically
- Savings goals: tells you how much to save per month to hit each deadline
- Debt payoff planner: months to payoff, debt-free date, total interest, extra-payment effect
- Bill tracker: tick off recurring bills month by month
- Works in Microsoft Excel, Google Sheets, Apple Numbers, LibreOffice. Printable (each tab fits one page).
- Instant digital download, personal-use license, no subscription, no bank login"""


def _prompt(v, brand):
    return f"""You are writing marketplace copy for a digital product sold on Etsy and Gumroad by the shop "{brand}".

Product: {v.name} (spreadsheet template)
Currency inside the template: {CURRENCY_NAMES[v.currency]} ({v.currency})
Color theme: {THEME_NAMES[v.theme]}
Price: {v.currency}{v.price:.2f}
Features (only claim these; do not invent features, testimonials, sales numbers or guarantees):
{FEATURES}

Audience: people who want to get their money organized for {v.year}, typically beginners. Write for buyers
in the countries that use this currency (spelling and wording to match).

Write:
- title and etsy_title (front-load the search keywords people actually type)
- description: hook line, what's inside, works-with, who it's for, how delivery works, and a final line
  "This is a digital product. No physical item will be shipped."
- 13 tags
- 6 Pinterest pins, each a different angle (saving money, paying off debt, new-year reset, couples, beginners, etc.)
- 8 social posts spread across reddit, facebook_group, instagram, tiktok (a 20-second video script), x and
  linkedin. Reddit and Facebook-group posts must lead with genuinely useful budgeting advice and mention the
  template only briefly at the end, because those communities remove ads. Put the placeholder {{link}} where the
  link should go."""


def _fallback(v, brand):
    cur = v.currency
    desc = f"""Stop wondering where your money went. Start {v.year} knowing exactly where it's going.

This all-in-one budget spreadsheet turns 10 minutes a week into total clarity about your money. Log what you earn and spend; the dashboard does the math.

WHAT'S INSIDE (7 tabs)
{FEATURES}

Amounts are shown in {cur}. Instant download after purchase: open in Excel, or in Google Sheets use File > Import > Upload. Start on the "Start Here" tab.

This is a digital product. No physical item will be shipped."""
    pins = [
        ("Where did my money go?", "Budget spreadsheet that shows where your money goes"),
        (f"My {v.year} money reset", f"{v.year} budget planner: start the year organized"),
        ("Pay off debt faster", "Debt payoff planner spreadsheet with debt-free date"),
        ("Save {}1,000 this year".format(cur), "Savings goal tracker: how much to save each month"),
        ("Budgeting for beginners", "Easy budget template for beginners (Excel + Google Sheets)"),
        ("10 minutes a week budget", "Simple weekly budget routine with an automatic dashboard"),
    ]
    return {
        "title": f"{v.year} Budget & Finance Planner | Excel + Google Sheets",
        "etsy_title": f"{v.year} Budget Planner Spreadsheet, Google Sheets & Excel Budget Template, Monthly Budget "
                      f"Tracker, Debt Payoff, Savings Tracker",
        "description": desc,
        "tags": ["budget spreadsheet", f"budget planner {v.year}", "google sheets budget", "excel budget",
                 "monthly budget", "debt payoff tracker", "savings tracker", "finance planner", "budget template",
                 "expense tracker", "bill tracker", "paycheck budget", "financial planner"],
        "pins": [{"headline": h, "title": t,
                  "description": f"{t}. Dashboard, savings goals, debt payoff and bill tracker in one {v.year} "
                                 f"spreadsheet. Works in Excel and Google Sheets. Instant download."}
                 for h, t in pins],
        "social_posts": [
            {"platform": "reddit", "text": "The budgeting habit that finally stuck for me: one 10-minute check-in every "
             "Sunday. Log the week's spending, compare each category to its budget, move money if something's over. "
             "Skip the apps that need your bank login; a simple spreadsheet works.\n\nI made the one I use into a "
             "template if anyone wants it: {link}"},
            {"platform": "facebook_group", "text": "Tip for anyone starting a budget for the new year: give every "
             "category a monthly number, then track only the difference between plan and actual. That's the whole "
             "trick.\n\nI built a spreadsheet that does the math automatically: {link}"},
            {"platform": "instagram", "text": f"POV: it's {v.year} and you actually know where your money goes 💸\n"
             "Dashboard, savings goals, debt payoff, bill tracker, all automatic.\nLink in bio 👆 #budgeting "
             "#moneytips #debtfree #savingmoney #budgetplanner"},
            {"platform": "tiktok", "text": "[0-3s] 'Where did my money go last year?' (show bank app, shrug)\n"
             "[3-12s] Screen-record: type one expense, dashboard updates, category turns red.\n"
             "[12-18s] Show Debt Payoff tab: debt-free date moves closer as you add an extra payment.\n"
             "[18-20s] 'Template in my bio.' #budgettok #moneytips #budgeting"},
            {"platform": "x", "text": f"Made a {v.year} budget spreadsheet: dashboard, savings goals, debt payoff "
             "date, bill tracker. Excel + Google Sheets. {link}"},
            {"platform": "linkedin", "text": "Small side project: I turned the budgeting spreadsheet I use into a "
             "template. Auto dashboard, savings-goal math, debt payoff planner. If it helps anyone plan "
             f"{v.year}: {{link}}"},
        ],
    }


def _clean(copy):
    tags = []
    for t in copy.get("tags", []):
        t = TAG_RE.sub("", t).strip().lower()[:20].strip()
        if t and t not in tags:
            tags.append(t)
    copy["tags"] = tags[:13]
    copy["etsy_title"] = copy.get("etsy_title", "")[:140]
    copy["title"] = copy.get("title", "")[:100]
    for p in copy.get("pins", []):
        p["headline"], p["title"], p["description"] = p["headline"][:60], p["title"][:100], p["description"][:500]
    return copy


def _ask_claude(v, brand):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": _prompt(v, brand)}],
        output_format=ListingCopy,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Claude returned no usable copy (stop_reason={resp.stop_reason})")
    return resp.parsed_output.model_dump()


def _digest(copy):
    body = {k: v for k, v in copy.items() if k not in ("source", "digest")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _needs_writing(existing, use_claude):
    if not existing:
        return True
    unedited = existing.get("digest") == _digest(existing)
    return use_claude and existing.get("source") == "template" and unedited


def run(ctx):
    brand = ctx.config.get("store", {}).get("brand", "our shop")
    use_claude = bool(ctx.env("ANTHROPIC_API_KEY"))
    written, fell_back = [], []
    for v in ctx.variants():
        if not _needs_writing(load_copy(ctx.root, v.id), use_claude):
            continue
        source = "template"
        if use_claude:
            try:
                copy, source = _ask_claude(v, brand), "claude"
            except Exception as e:  # any API problem: keep the pipeline moving with template copy
                ctx.log(f"  ! Claude copy failed for {v.id}: {e}")
                copy = _fallback(v, brand)
                fell_back.append(v.id)
        else:
            copy = _fallback(v, brand)
        copy = _clean(copy)
        if ctx.config.get("store", {}).get("disclose_ai", True):
            copy["description"] += "\n\nDesigned with the help of AI tools and checked by the shop owner."
        copy["source"] = source
        copy["digest"] = _digest(copy)
        if not ctx.dry_run:
            path = copy_path(ctx.root, v.id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(copy, indent=2, ensure_ascii=False) + "\n")
        written.append(f"{v.id} ({source})")
    if not written:
        return Result.skipped("copy already written for every variant")
    msg = f"wrote copy for {', '.join(written)}"
    if not use_claude:
        msg += ". Template copy used: set ANTHROPIC_API_KEY for AI-written copy"
    if fell_back:
        msg += f". Claude failed for {len(fell_back)}; used templates"
    return Result.ok(msg)
