# Budget Planner Shop + Autopilot

A sellable digital product (budget & finance planner spreadsheet) and a set of agents that build, list, promote and track it automatically, once a day, on GitHub Actions.

**Start here:** [`SETUP.md`](SETUP.md). **Check on it:** [`reports/STATUS.md`](reports/STATUS.md).

```
             ┌──────────────── daily GitHub Action ────────────────┐
autopilot.toml → Factory → Copywriter → Etsy → Gumroad → Pinterest → Social → Sales → Strategist
 (catalog)      build      Claude       list   launch    3 pins/day  posts    orders  weekly plan
                files      copy         sell   discount               to paste report  (+ new variants)
                                                      state/ + reports/ committed back ┘
```

| Path | What it is |
|---|---|
| `autopilot.toml` | Catalog of variants (year, currency, theme, price) and agent settings |
| `autopilot/agents/` | One file per agent |
| `scripts/build_planner.py` | Generates the spreadsheet; `build(out, year, currency, theme)` |
| `state/` | What the agents have done (listing ids, pin rotation, copy). Committed by the bot. |
| `reports/` | `STATUS.md`, `sales.csv`, daily sales reports, weekly strategy, today's posts |
| `product/`, `LISTING.md`, `LAUNCH_PLAN.md` | The original 2027 product, its listing copy and launch plan |

```bash
pip install -r requirements.txt
python -m autopilot status            # what's connected, what's missing (changes nothing)
python -m autopilot build             # build all variants + copy into dist/
python -m autopilot daily --dry-run   # full run without sending anything
python -m pytest -q tests             # tests (pip install -r requirements-dev.txt)
```
