# Hospital Directory by Uddgam — All India

Free, real data from OpenStreetMap (Overpass API). No API keys, no paid services.

## How the data stays safe
- **First run:** fetches every state/UT and saves it.
- **Every day (3:30 PM IST):** fetches again, **compares** with the saved data and replaces a state only if something changed (the old file is first copied to `backup/`).
- **If a fetch fails, returns nothing, or returns far fewer hospitals** (under 60% of before), the saved data is kept and the site keeps showing it.
- The saved data lives on the repo's **`data` branch** (do not delete it). Visitors' browsers also keep a copy, so the page can show saved data if the site is briefly unreachable.
- Each run writes a per-state report to the Actions run summary.

## Files
- `index.html` — the directory (natural-language search, filters, copy-only, dark mode)
- `fetch_hospitals.py` — fetch + compare + backup logic
- `robots.txt` — asks crawlers to stay out
- `.github/workflows/daily.yml` — daily job + deploy to GitHub Pages

## Set up
1. Settings → Pages → **Source: GitHub Actions**.
2. Actions → "Daily hospital refresh & deploy" → **Run workflow**. For a quick first test type `TG` in the box (one state, a few minutes); later run it blank for all India.
3. Check the run's **Summary** page for the per-state result.

## Run locally
    python3 fetch_hospitals.py          # all states   (or: python3 fetch_hospitals.py TG KA)
    python3 -m http.server              # open http://localhost:8000

Data © OpenStreetMap contributors. May be incomplete — verify with the hospital.
