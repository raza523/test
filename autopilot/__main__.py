"""Autopilot: runs the shop's agents in order.

  python -m autopilot daily [--dry-run] [--only factory,etsy,...]   run the daily pipeline
  python -m autopilot build                                         build products + copy only
  python -m autopilot status                                        show what's set up and what isn't
  python -m autopilot etsy-auth                                     one-time Etsy login
  python -m autopilot etsy-taxonomy planner                         find the Etsy category id
  python -m autopilot gumroad-products                              list Gumroad product ids
  python -m autopilot pinterest-boards                              list Pinterest board ids
"""
import argparse
import sys
from datetime import date

from . import core
from .agents import copywriter, etsy, factory, gumroad, pinterest, sales, social, strategist

PIPELINE = [
    ("factory", "Product Factory", factory),
    ("copywriter", "Copywriter", copywriter),
    ("etsy", "Etsy Publisher", etsy),
    ("gumroad", "Gumroad Promoter", gumroad),
    ("pinterest", "Pinterest Marketer", pinterest),
    ("social", "Social Queue", social),
    ("sales", "Sales Analyst", sales),
    ("strategist", "Strategist", strategist),
]
ICONS = {"ok": "✅", "skipped": "➖", "needs_setup": "⚙️", "error": "❌"}


def make_ctx(dry_run=False, today=None, root=core.ROOT):
    core.load_dotenv(root)
    return core.Ctx(root=root, config=core.load_config(root), state=core.load_state(root),
                    today=today or date.today(), dry_run=dry_run)


def run_pipeline(ctx, only=None):
    results = []
    for key, label, agent in PIPELINE:
        if only and key not in only:
            continue
        ctx.log(f"▶ {label}")
        try:
            res = agent.run(ctx)
        except Exception as e:  # one broken agent must not stop the others
            res = core.Result("error", f"{type(e).__name__}: {e}")
        ctx.log(f"  {ICONS[res.status]} {res.summary}")
        results.append((key, label, res))
    if not ctx.dry_run:
        core.save_state(ctx.root, ctx.state)
        write_status(ctx, results)
    return results


def write_status(ctx, results):
    lines = [f"# Autopilot status: {ctx.today.isoformat()}", "", "| Agent | Result | Details |", "|---|---|---|"]
    lines += [f"| {label} | {ICONS[r.status]} {r.status} | {r.summary} |" for _, label, r in results]
    todo = [f"- **{label}:** {r.summary}" for _, label, r in results if r.status in ("needs_setup", "error")]
    lines += ["", "## Needs you", ""] + (todo or ["- Nothing. Everything is running on its own."])
    last = ctx.state.get("sales", {}).get("last_summary")
    if last:
        lines += ["", "## Sales", "", f"- Last 7 days: {last['7d'][0]} orders, {last['7d'][1]}",
                  f"- All time: {last['all'][0]} orders, {last['all'][1]}"]
    ctx.reports.mkdir(parents=True, exist_ok=True)
    (ctx.reports / "STATUS.md").write_text("\n".join(lines) + "\n")


def etsy_taxonomy(query):
    import os

    import requests
    core.load_dotenv()
    key = f"{os.environ['ETSY_API_KEY']}:{os.environ['ETSY_SHARED_SECRET']}"
    nodes = requests.get("https://api.etsy.com/v3/application/seller-taxonomy/nodes",
                         headers={"x-api-key": key}, timeout=60).json()["results"]

    def walk(ns, path):
        for n in ns:
            p = f"{path} > {n['name']}" if path else n["name"]
            if query.lower() in n["name"].lower():
                print(f"{n['id']:>6}  {p}")
            walk(n.get("children", []), p)
    walk(nodes, "")


def list_ids(command):
    ctx = make_ctx()
    if command == "gumroad-products":
        for p in gumroad.call(ctx, "GET", "/products").get("products", []):
            print(f"{p['id']}  {p.get('name', '')}  {p.get('short_url', '')}")
    else:
        bearer = {"Authorization": f"Bearer {pinterest.token(ctx)}"}
        for b in pinterest.http.request(ctx, "GET", f"{pinterest.API}/boards", headers=bearer).get("items", []):
            print(f"{b['id']}  {b.get('name', '')}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autopilot", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["daily", "build", "status", "etsy-auth", "etsy-taxonomy",
                                              "gumroad-products", "pinterest-boards"])
    ap.add_argument("query", nargs="?", default="planner")
    ap.add_argument("--dry-run", action="store_true", help="send no writes to any marketplace, save nothing")
    ap.add_argument("--only", help="comma-separated agents to run: " + ",".join(k for k, _, _ in PIPELINE))
    args = ap.parse_args(argv)

    if args.command == "etsy-auth":
        import os

        from . import etsy_auth
        core.load_dotenv()
        cfg = core.load_config().get("etsy", {})
        etsy_auth.main(os.environ["ETSY_API_KEY"], os.environ["ETSY_SHARED_SECRET"],
                       cfg.get("redirect_uri", "http://localhost:3003/oauth/redirect"))
        return 0
    if args.command == "etsy-taxonomy":
        etsy_taxonomy(args.query)
        return 0
    if args.command in ("gumroad-products", "pinterest-boards"):
        list_ids(args.command)
        return 0

    ctx = make_ctx(dry_run=args.dry_run or args.command == "status")
    if args.command == "status":
        # A dry run of everything: shows what is configured without changing anything.
        results = run_pipeline(ctx)
    else:
        only = set(args.only.split(",")) if args.only else ({"factory", "copywriter"} if args.command == "build" else None)
        results = run_pipeline(ctx, only)
    return 1 if any(r.status == "error" for _, _, r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
