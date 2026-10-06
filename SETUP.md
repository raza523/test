# Autopilot setup (one time, about 45 minutes)

After this, a GitHub Action runs every agent once a day on its own. You don't need a computer switched on.

| Agent | What it does by itself | Needs |
|---|---|---|
| **Product Factory** | Builds every product variant (year × currency × color) plus listing images | nothing |
| **Copywriter** | Writes titles, descriptions, 13 Etsy tags, Pinterest pins and social posts per variant | optional: `ANTHROPIC_API_KEY` (built-in templates otherwise) |
| **Etsy Publisher** | Creates listings, uploads images and the download file, publishes | Etsy keys (step 3) |
| **Gumroad Promoter** | Starts the launch discount code, and ends it on the date you set | Gumroad token (step 2) |
| **Pinterest Marketer** | Designs and posts 3 pins a day that link to your listings | Pinterest token (step 4) |
| **Sales Analyst** | Pulls every order into `reports/sales.csv` and writes `reports/daily/<date>.md` | Gumroad and/or Etsy |
| **Strategist** | Weekly report on what to make next; can add new variants by itself | optional: `ANTHROPIC_API_KEY` |
| **Social Queue** | Writes today's ready-to-paste posts in `reports/todo/<date>.md` | a store link |

Check how things are going any time in **`reports/STATUS.md`**. It lists what ran and anything that needs you.

> **What stays manual, and why:** creating your marketplace accounts and payout details, one login click each for Etsy and Pinterest, and creating the Gumroad product page once (Gumroad's API can't upload the file). Reddit, Facebook groups and TikTok ban bots and remove automated promotion, so the Social Queue writes those posts for you to paste. Posting them is optional and takes about 5 minutes.

Add each secret below in GitHub under **repo → Settings → Secrets and variables → Actions → New repository secret**. To run locally instead, put them in a `.env` file in the repo root (it's git-ignored).

---

## 1. Turn on the daily run
1. On GitHub, open the **Actions** tab and enable workflows if asked.
2. Schedules only run from the repository's **default branch**. Make sure the branch with this code is the default, or merge it into the default branch.
3. Run it once now: **Actions → Autopilot → Run workflow**. Tick "Dry run" for the first try. Then open `reports/STATUS.md`.

## 2. Gumroad (about 10 minutes)
1. Create the product once by hand: Gumroad → Products → New product → Digital product. Upload the `.xlsx` and images. Download them from the latest **Autopilot** run's "products" artifact, or use `product/` in this repo. Publish it.
2. Settings → Advanced → Applications → create an application → **Generate access token**. Save it as the secret `GUMROAD_ACCESS_TOKEN`.
3. Find the product id with `python -m autopilot gumroad-products` (or read it from the product's edit URL). Add it to `autopilot.toml`:
   ```toml
   [gumroad.products]
   "budget-2027-usd-sage" = "the-product-id"
   ```
4. Put the product's public link in `autopilot.toml` → `[store] gumroad_url`. Pins and posts use it until Etsy listings are live.
5. Set `launch_until` to the last day of your launch discount.

## 3. Etsy (about 15 minutes)
1. Open your Etsy shop (identity and payment verification can take a day). Then register an app at **etsy.com/developers/register**.
2. In the app's settings, add the callback URL `http://localhost:3003/oauth/redirect`.
3. Save the app's **keystring** as `ETSY_API_KEY` and its **shared secret** as `ETSY_SHARED_SECRET`.
4. On your computer (needs Python 3.11+), from this repo:
   ```bash
   pip install -r requirements.txt
   echo "ETSY_API_KEY=..." >> .env && echo "ETSY_SHARED_SECRET=..." >> .env
   python -m autopilot etsy-auth
   ```
   It prints `ETSY_REFRESH_TOKEN` and `ETSY_SHOP_ID`. Save both as secrets.
5. Find the category: `python -m autopilot etsy-taxonomy planner`. Put the best match's id in `autopilot.toml` → `[etsy] taxonomy_id`.
6. Keep Etsy's login alive: Etsy rotates the refresh token. Create a GitHub **fine-grained personal access token** for this repo with "Secrets: Read and write" permission, and save it as `GH_PAT`. Without it, run `etsy-auth` again every 90 days.
7. The first runs create **drafts**. Look at one on Etsy, then set `[etsy] publish = true` and the agent publishes all of them. Etsy charges $0.20 per listing.

## 4. Pinterest (about 10 minutes)
1. Use a free **Pinterest Business** account. Create a board, e.g. "Budget Planner".
2. Create an app at **developers.pinterest.com** and generate an access token with the scopes `boards:read`, `boards:write`, `pins:read`, `pins:write`. Save it as `PINTEREST_ACCESS_TOKEN`.
   - Tokens expire. For hands-off renewal, also save `PINTEREST_REFRESH_TOKEN`, `PINTEREST_APP_ID` and `PINTEREST_APP_SECRET`.
3. Get the board id with `python -m autopilot pinterest-boards` and save it as `PINTEREST_BOARD_ID`.
4. New apps start in **Trial** access, which only posts to your own account. Request **Standard** access in the app dashboard.

## 5. Claude (optional, recommended)
Save an Anthropic API key as `ANTHROPIC_API_KEY`. The Copywriter then writes original copy per variant, and the Strategist reads your sales each week. Usage is a few calls per variant plus one a week, so it typically costs cents per month; check current pricing in the Anthropic Console.

Copy is saved in `state/copy/<variant>.json`. Edit those files freely: the agent never overwrites them. Delete a file to have it rewritten.

---

## Day-to-day controls (all in `autopilot.toml`)
- **Add a product:** add a `[[variants]]` block. The next run builds it, writes copy, lists it and starts pinning it.
- **Let the shop grow by itself:** `[strategist] auto_expand = true`, capped by `max_variants`.
- **Go live automatically on Etsy:** `[etsy] publish = true`.
- **Pins per day:** `[pinterest] pins_per_day`.
- **Pause an agent:** `enabled = false` under `[etsy]` or `[pinterest]`, or run `python -m autopilot daily --only sales,strategist`.
- **Try without changing anything:** `python -m autopilot daily --dry-run`.
