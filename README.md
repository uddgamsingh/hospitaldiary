# Hospital Directory by Uddgam — All India

Free, real data from OpenStreetMap (Overpass API). No API keys, no paid services.

## Files
- `index.html` — the directory: natural-language search, state/district, filters, near-me, copy-only (no download), dark mode
- `fetch_hospitals.py` — daily job; writes `data/index.json` + one `data/<STATE>.dat` per state/UT
- `.github/workflows/daily.yml` — runs the job every day at 02:00 IST and deploys to GitHub Pages

## Host on GitHub Pages (recommended)
1. Push these files to a repo.
2. Settings → Pages → **Source: GitHub Actions**.
3. Actions tab → "Daily hospital refresh & deploy" → **Run workflow** (first run takes 30–90 min; it then repeats daily).
Data is rebuilt and published on every run, so it is never committed to the repo.

## Run locally
    python3 fetch_hospitals.py          # all states   (or: python3 fetch_hospitals.py TG KA)
    python3 -m http.server              # open http://localhost:8000

Data © OpenStreetMap contributors. May be incomplete — verify with the hospital.
