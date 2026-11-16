#!/usr/bin/env python3
"""Hospital Directory by Uddgam - daily data job (all India).

Pulls every hospital for each Indian state / UT from OpenStreetMap through the
free Overpass API (no key) and writes:
    data/index.json        list of states, counts, timestamps
    data/<STATE>.dat       compressed, scrambled hospital records for that state

Run:      python3 fetch_hospitals.py            (all states)
          python3 fetch_hospitals.py TG KA      (only some states)
          python3 fetch_hospitals.py --out site/data
Daily:    use the included GitHub Actions workflow, or cron:
          0 2 * * * cd /path/to/folder && python3 fetch_hospitals.py
"""
import json, os, re, sys, time, urllib.parse, urllib.request, zlib
from datetime import datetime, timezone

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
# code, name, regex of ISO3166-2 values used in OSM (some codes changed over time)
STATES = [
    ("AN", "Andaman and Nicobar Islands", "IN-AN"), ("AP", "Andhra Pradesh", "IN-AP"),
    ("AR", "Arunachal Pradesh", "IN-AR"), ("AS", "Assam", "IN-AS"), ("BR", "Bihar", "IN-BR"),
    ("CH", "Chandigarh", "IN-CH"), ("CG", "Chhattisgarh", "IN-(CG|CT)"),
    ("DH", "Dadra and Nagar Haveli and Daman and Diu", "IN-(DH|DN|DD)"), ("DL", "Delhi", "IN-DL"),
    ("GA", "Goa", "IN-GA"), ("GJ", "Gujarat", "IN-GJ"), ("HR", "Haryana", "IN-HR"),
    ("HP", "Himachal Pradesh", "IN-HP"), ("JK", "Jammu and Kashmir", "IN-JK"),
    ("JH", "Jharkhand", "IN-JH"), ("KA", "Karnataka", "IN-KA"), ("KL", "Kerala", "IN-KL"),
    ("LA", "Ladakh", "IN-LA"), ("LD", "Lakshadweep", "IN-LD"), ("MP", "Madhya Pradesh", "IN-MP"),
    ("MH", "Maharashtra", "IN-MH"), ("MN", "Manipur", "IN-MN"), ("ML", "Meghalaya", "IN-ML"),
    ("MZ", "Mizoram", "IN-MZ"), ("NL", "Nagaland", "IN-NL"), ("OD", "Odisha", "IN-(OD|OR)"),
    ("PB", "Punjab", "IN-PB"), ("PY", "Puducherry", "IN-PY"), ("RJ", "Rajasthan", "IN-RJ"),
    ("SK", "Sikkim", "IN-SK"), ("TN", "Tamil Nadu", "IN-TN"), ("TG", "Telangana", "IN-(TG|TS)"),
    ("TR", "Tripura", "IN-TR"), ("UP", "Uttar Pradesh", "IN-UP"), ("UK", "Uttarakhand", "IN-(UK|UT)"),
    ("WB", "West Bengal", "IN-WB"),
]

def flat_query(iso):
    return f"""[out:json][timeout:300][maxsize:1073741824];
area["ISO3166-2"~"^{iso}$"]->.s;
( nwr["amenity"="hospital"](area.s); nwr["healthcare"="hospital"](area.s); );
out center tags;"""

def district_query(iso, level):
    # for each district boundary: print its name, then the ids of the hospitals inside it
    return f"""[out:json][timeout:300][maxsize:1073741824];
area["ISO3166-2"~"^{iso}$"]->.s;
rel(area.s)["boundary"="administrative"]["admin_level"="{level}"]->.dists;
foreach.dists->.d(
  .d out tags;
  .d map_to_area->.da;
  ( nwr["amenity"="hospital"](area.da); nwr["healthcare"="hospital"](area.da); );
  out ids;
);"""

def overpass(query, tries=3):
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for _ in range(tries):
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "uddgam-hospital-directory/2.0"})
                with urllib.request.urlopen(req, timeout=420) as r:
                    return json.load(r)
            except Exception as e:
                last = e
                print(f"   {url.split('/')[2]} failed: {e}", file=sys.stderr)
                time.sleep(8)
    raise last

GOV = re.compile(r"\b(gov|govt|government|public|municipal|esi|esic|railway|army|military|district hospital|civil hospital|area hospital|phc|chc|aiims|primary health|community health|sub[- ]?centre)\b", re.I)
PVT = re.compile(r"\b(private|pvt|trust|charit\w*|ngo|ltd|limited|corporate|mission|christian|foundation|nursing home)\b", re.I)

def kind_of(t, name):
    ot = (t.get("operator:type") or t.get("ownership") or "").lower()
    if ot in ("government", "public", "state", "central"): return "gov"
    if ot in ("private", "community", "religious", "charitable", "ngo"): return "pvt"
    s = f'{t.get("operator","")} {name}'
    if GOV.search(s): return "gov"
    if PVT.search(s): return "pvt"
    return ""

def normalize(el, state_code, district=""):
    t = el.get("tags") or {}
    name = (t.get("name") or t.get("name:en") or "").strip()
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    if not name or lat is None or lon is None:
        return None
    city = t.get("addr:city") or t.get("addr:town") or t.get("addr:village") or ""
    addr = ", ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:suburb"),
                                 city, t.get("addr:district"), t.get("addr:postcode")] if x)
    beds = t.get("beds") or t.get("capacity") or ""
    m = re.search(r"\d+", beds)
    rec = {
        "id": el["type"][0] + str(el["id"]),
        "name": name,
        "te": t.get("name:te") or t.get("name:hi") or "",
        "dist": district or t.get("addr:district") or city or "",
        "addr": addr,
        "phone": t.get("phone") or t.get("contact:phone") or "",
        "email": t.get("email") or t.get("contact:email") or "",
        "web": t.get("website") or t.get("contact:website") or "",
        "hours": t.get("opening_hours") or "",
        "beds": int(m.group()) if m else "",
        "er": t.get("emergency") or "",
        "op": t.get("operator") or "",
        "spec": "; ".join(s.strip().replace("_", " ") for s in (t.get("healthcare:speciality") or "").split(";") if s.strip()),
        "wheel": t.get("wheelchair") or "",
        "kind": kind_of(t, name),
        "lat": round(lat, 5), "lon": round(lon, 5),
    }
    return {k: v for k, v in rec.items() if v not in ("", None)}

KEY = b"uddgam-hospitals"   # must match readDat() in index.html
def scramble(b):
    return bytes(c ^ KEY[i % len(KEY)] for i, c in enumerate(b))

def fetch_state(code, iso):
    data = overpass(flat_query(iso))
    els = data.get("elements", [])
    # best-effort: tag every hospital with its district (admin_level 5, else 6)
    id_to_dist = {}
    for level in (5, 6):
        try:
            cur, found = "", 0
            for el in overpass(district_query(iso, level)).get("elements", []):
                tg = el.get("tags") or {}
                if tg.get("boundary") == "administrative":
                    cur, found = (tg.get("name:en") or tg.get("name") or "").replace(" District", "").strip(), found + 1
                elif cur:
                    id_to_dist.setdefault(el["type"][0] + str(el["id"]), cur)
            if found:
                break
        except Exception as e:
            print(f"   district lookup (level {level}) skipped: {e}", file=sys.stderr)
    seen, out = set(), []
    for el in els:
        rec = normalize(el, code, id_to_dist.get(el["type"][0] + str(el["id"]), ""))
        if rec and rec["id"] not in seen:
            seen.add(rec["id"]); out.append(rec)
    out.sort(key=lambda r: r["name"].lower())
    return out

def main(argv):
    outdir = "data"
    if "--out" in argv:
        i = argv.index("--out"); outdir = argv[i + 1]; del argv[i:i + 2]
    only = {a.upper() for a in argv}
    os.makedirs(outdir, exist_ok=True)
    idx_path = os.path.join(outdir, "index.json")
    old = {}
    if os.path.exists(idx_path):
        try: old = {s["code"]: s for s in json.load(open(idx_path))["states"]}
        except Exception: pass
    states, ok = [], 0
    for code, name, iso in STATES:
        if only and code not in only:
            if code in old: states.append(old[code])
            continue
        print(f"[{code}] {name} ...", flush=True)
        try:
            recs = fetch_state(code, iso)
            if not recs: raise RuntimeError("no hospitals returned")
            at = datetime.now(timezone.utc).isoformat()
            raw = json.dumps({"code": code, "name": name, "at": at, "hospitals": recs}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            with open(os.path.join(outdir, f"{code}.dat"), "wb") as f:   # compressed + scrambled: no plain-JSON dump
                f.write(scramble(zlib.compress(raw, 9)))
            states.append({"code": code, "name": name, "count": len(recs), "at": at}); ok += 1
            print(f"   {len(recs)} hospitals")
        except Exception as e:
            print(f"   FAILED: {e}", file=sys.stderr)
            states.append(old.get(code, {"code": code, "name": name, "count": 0, "at": ""}))
        time.sleep(6)   # be polite to the free servers
    idx = {"fetched_at": datetime.now(timezone.utc).isoformat(),
           "total": sum(s["count"] for s in states), "states": states}
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Done: {ok} states updated, {idx['total']} hospitals total.")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
