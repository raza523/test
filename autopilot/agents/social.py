"""Social Queue: prepares today's ready-to-paste posts for Reddit, Facebook groups, TikTok, etc.

These platforms ban automated or bot posting in the places buyers hang out, and breaking that gets
accounts banned, so this agent writes the posts and you paste them (about 5 minutes, optional).
"""
from ..core import Result, load_copy


def run(ctx):
    per_day = int(ctx.config.get("social", {}).get("posts_per_day", 2))
    pool = []
    for v in ctx.variants():
        copy, link = load_copy(ctx.root, v.id), ctx.store_link(v)
        if copy and link:
            pool += [(v, p, link) for p in copy.get("social_posts", [])]
    if not pool:
        return Result.needs_setup("no store link yet (live Etsy listing or [store] gumroad_url)")
    st = ctx.state.setdefault("social", {"cursor": 0})
    if st.get("last_day") == ctx.today.isoformat():
        return Result.skipped("today's posts already prepared")
    picks = [pool[(st["cursor"] + i) % len(pool)] for i in range(min(per_day, len(pool)))]
    lines = [f"# Today's posts: {ctx.today.isoformat()}", "",
             "Optional, about 5 minutes. Copy, paste, post. Check each group's self-promotion rules first.", ""]
    for v, p, link in picks:
        lines += [f"## {p['platform'].replace('_', ' ').title()} ({v.year} {v.currency} {v.theme})", "", "```",
                  p["text"].replace("{link}", link), "```", ""]
    if not ctx.dry_run:
        out = ctx.reports / "todo" / f"{ctx.today.isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines))
        st["cursor"] = (st["cursor"] + len(picks)) % len(pool)
        st["last_day"] = ctx.today.isoformat()
    return Result.ok(f"prepared {len(picks)} post(s) in reports/todo/{ctx.today.isoformat()}.md")
