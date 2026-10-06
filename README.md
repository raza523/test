# 2027 Budget & Finance Planner (digital product)

A ready-to-sell spreadsheet template: Excel + Google Sheets compatible.

| File | What it is |
|---|---|
| `product/2027-Budget-Finance-Planner.xlsx` | **The product.** Upload this to Gumroad / Etsy. |
| `product/listing-images/` | Screenshots for your listing (dashboard first). |
| `LISTING.md` | Title, description, price, Etsy tags. Copy and paste. |
| `LAUNCH_PLAN.md` | Step-by-step plan to get first sales in 48 hours. |
| `scripts/build_planner.py` | Regenerates the product (change `YEAR`, categories, colors to make variations). |

```bash
python3 scripts/build_planner.py                       # build the product file
python3 scripts/build_planner.py demo.xlsx --demo      # version with a full year of sample data (for screenshots)
```
