#!/usr/bin/env python3
"""Hospital Directory by Uddgam - daily data job (all India).

Pulls every hospital for each Indian state / UT from OpenStreetMap through the
free Overpass API (no key) and writes:
    data/index.json        list of states, counts, timestamps
    data/<STATE>.dat       compressed, scrambled hospital records for that state

First run fetches everything. Every later run COMPARES new data with the saved
data and only replaces a state's file when something really changed. The old
file is copied to data/backup/ first. If a fetch fails, returns nothing, or
returns far fewer hospitals than before, the saved data is kept untouched.

Run:      python3 fetch_hospitals.py            (all states)
          python3 fetch_hospitals.py TG KA      (only some states)
          python3 fetch_hospitals.py --out site/data
Daily:    use the included GitHub Actions workflow, or cron:
          0 2 * * * cd /path/to/folder && python3 fetch_hospitals.py
"""
import hashlib, json, os, re, shutil, sys, time, urllib.parse, urllib.request, zlib
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

def overpass(query, tries=3, timeout=420, endpoints=None):
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for _ in range(tries):
        for url in (endpoints or ENDPOINTS):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "uddgam-hospital-directory/2.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
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

DIST_FAILS = 0   # stop trying district lookups if the servers keep refusing them

def fetch_state(code, iso, prev=None):
    global DIST_FAILS
    prev = prev or {}
    data = overpass(flat_query(iso))
    els = data.get("elements", [])
    id_to_dist = {}
    if DIST_FAILS < 3:   # best-effort: tag every hospital with its district (admin_level 5, else 6)
        for level in (5, 6):
            try:
                cur, found = "", 0
                for el in overpass(district_query(iso, level), tries=1, timeout=200).get("elements", []):
                    tg = el.get("tags") or {}
                    if tg.get("boundary") == "administrative":
                        cur, found = (tg.get("name:en") or tg.get("name") or "").replace(" District", "").strip(), found + 1
                    elif cur:
                        id_to_dist.setdefault(el["type"][0] + str(el["id"]), cur)
                DIST_FAILS = 0
                if found:
                    break
            except Exception as e:
                DIST_FAILS += 1
                print(f"   district lookup (level {level}) skipped: {e}", file=sys.stderr)
                break
    seen, out = set(), []
    for el in els:
        hid = el["type"][0] + str(el["id"])
        # if today's district lookup gave nothing, keep the district we already had
        rec = normalize(el, code, id_to_dist.get(hid) or prev.get(hid, ""))
        if rec and rec["id"] not in seen:
            seen.add(rec["id"]); out.append(rec)
    out.sort(key=lambda r: (r["name"].lower(), r["id"]))
    return out

# ---------- storage helpers ----------
KEY = b"uddgam-hospitals"   # must match readDat() in index.html
def scramble(b):
    return bytes(c ^ KEY[i % len(KEY)] for i, c in enumerate(b))

def read_dat(path):
    try:
        with open(path, "rb") as f:
            return json.loads(zlib.decompress(scramble(f.read())).decode("utf-8"))
    except Exception:
        return None

def write_dat(path, obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(scramble(zlib.compress(raw, 9)))
    os.replace(tmp, path)          # atomic: a crash can never leave a half-written file

def digest(recs):
    return hashlib.sha256(json.dumps(recs, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def diff(old, new):
    o = {r["id"]: r for r in old}; n = {r["id"]: r for r in new}
    return {"added": len(n.keys() - o.keys()), "removed": len(o.keys() - n.keys()),
            "modified": sum(1 for k in n.keys() & o.keys() if n[k] != o[k])}

def now():
    return datetime.now(timezone.utc).isoformat()

def write_index(outdir, states):
    ats = [s["at"] for s in states if s.get("at")]
    idx = {"fetched_at": max(ats) if ats else now(), "checked_at": now(),
           "total": sum(s["count"] for s in states), "states": states}
    tmp = os.path.join(outdir, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(outdir, "index.json"))
    return idx

def main(argv):
    outdir, force = "data", False
    if "--out" in argv:
        i = argv.index("--out"); outdir = argv[i + 1]; del argv[i:i + 2]
    if "--force" in argv:
        argv.remove("--force"); force = True
    only = {a.upper() for a in argv}
    os.makedirs(os.path.join(outdir, "backup"), exist_ok=True)
    idx_path = os.path.join(outdir, "index.json")
    old = {}
    try: old = {s["code"]: s for s in json.load(open(idx_path))["states"]}
    except Exception: pass

    states, report = [], []
    for code, name, iso in STATES:
        path = os.path.join(outdir, f"{code}.dat")
        prev = old.get(code, {"code": code, "name": name, "count": 0, "at": "", "status": "pending"})
        old_obj = read_dat(path)
        old_recs = (old_obj or {}).get("hospitals", [])
        if not os.path.exists(path): prev = {**prev, "count": 0, "at": ""}
        if only and code not in only:
            states.append(prev); continue
        print(f"[{code}] {name} ...", flush=True)
        entry = dict(prev, code=code, name=name, checked=now())
        try:
            recs = fetch_state(code, iso, {r["id"]: r.get("dist", "") for r in old_recs})
            if not recs:
                raise RuntimeError("server returned no hospitals")
            if old_recs and len(recs) < 0.6 * len(old_recs) and not force:
                raise RuntimeError(f"suspicious drop {len(old_recs)} -> {len(recs)}; kept saved data")
            if old_recs and digest(recs) == digest(old_recs):
                entry.update(status="unchanged"); entry.pop("error", None); entry.pop("changes", None)
                msg = f"unchanged ({len(recs)})"
            else:
                ch = diff(old_recs, recs) if old_recs else {"added": len(recs), "removed": 0, "modified": 0}
                if old_obj and os.path.exists(path):
                    shutil.copy2(path, os.path.join(outdir, "backup", f"{code}.dat"))   # keep previous version
                at = now()
                write_dat(path, {"code": code, "name": name, "at": at, "hospitals": recs})
                entry.update(count=len(recs), at=at, status="updated" if old_recs else "new", changes=ch); entry.pop("error", None)
                msg = f"{entry['status']} ({len(recs)}; +{ch['added']} -{ch['removed']} ~{ch['modified']})"
        except Exception as e:
            entry.update(status="failed" if not old_recs else "stale", error=str(e)[:160])
            msg = f"{entry['status']}: {e}"
            print(f"   {msg}", file=sys.stderr)
        print(f"   {msg}")
        report.append(f"| {code} | {name} | {msg} |")
        states.append(entry)
        write_index(outdir, states + [old.get(c, {"code": c, "name": n, "count": 0, "at": ""}) for c, n, _ in STATES[len(states):]])  # save progress after every state
        time.sleep(6)   # be polite to the free servers
    idx = write_index(outdir, states)
    with open(os.path.join(outdir, "run_report.md"), "w", encoding="utf-8") as f:
        f.write(f"### Hospital data run {idx['checked_at']}\n\n| Code | State | Result |\n|---|---|---|\n" + "\n".join(report) + f"\n\n**Total hospitals served: {idx['total']}**\n")
    print(f"Done. {idx['total']} hospitals served.")
    return 0 if idx["total"] > 0 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
