"""Tigray OSINT collector. Run by GitHub Actions every few hours.
Steps: 1) gather headlines  2) ask Gemini to turn them into structured events
       3) grade each event with plain rules (not by the AI)  4) save data/events.json
"""
import os, json, re, datetime as dt
from urllib.parse import urlparse
import feedparser, requests
import time

MODEL = os.environ.get("MODEL", "gemini-flash-latest")   # change here if Google renames models
API_KEY = os.environ.get("GEMINI_API_KEY", "")
OUT = "data/events.json"
TODAY = dt.date.today().isoformat()
KEEP_DAYS = 45          # automatic events older than this are dropped
MAX_ITEMS = 60          # headlines sent to the AI per run (controls usage)

# ---- 1. WHERE WE LOOK (edit freely) ------------------------------------
FEEDS = [
    "https://news.google.com/rss/search?q=Tigray+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Mekelle+OR+TPLF+OR+Afar+OR+Eritrea+Ethiopia+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://www.aljazeera.com/xml/rss/all.xml",
]
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
KEYWORDS = ["tigray", "tplf", "mekelle", "mekele", "eritrea", "afar", "amhara", "fano", "abiy", "ethiopia"]

# Outlets we treat as independent, professional newsrooms
WIRES = ["reuters", "associated press", "ap news", "apnews", "afp", "al jazeera", "bbc", "france 24", "dw", "the guardian", "new york times"]

# Known places -> map position (approximate). Add more as needed.
PLACES = {
 "Mekelle": (13.50, 39.47), "Alamata": (12.42, 39.55), "Shire": (14.10, 38.28),
 "Axum": (14.13, 38.72), "Adwa": (14.17, 38.90), "Adigrat": (14.28, 39.46),
 "Abala": (13.38, 39.99), "Erebti": (13.30, 40.12), "Megale": (13.00, 40.35),
 "Semera": (11.79, 41.00), "Kobo": (12.15, 39.63), "Sekota": (12.63, 39.03),
 "Lalibela": (12.03, 39.04), "Dessie": (11.13, 39.63), "Woldia": (11.83, 39.60),
 "Addis Ababa": (9.03, 38.74), "Asmara": (15.34, 38.93), "Bahir Dar": (11.59, 37.39),
 "Gondar": (12.60, 37.47), "Humera": (14.30, 36.60), "Zalambessa": (14.52, 39.55),
}

def outlet_of(entry):
    src = entry.get("source")
    if src and src.get("title"):
        return src["title"]
    return urlparse(entry.get("link", "")).netloc.replace("www.", "")

# ---- 2. GATHER ---------------------------------------------------------
def gather():
    items, seen = [], set()
    def add(title, outlet, url, summary=""):
        k = re.sub(r"\W+", " ", title.lower()).strip()
        if k and k not in seen:
            seen.add(k); items.append({"title": title, "outlet": outlet, "url": url, "summary": summary[:300]})
    for f in FEEDS:
        try:
            for e in feedparser.parse(f).entries[:40]:
                text = (e.get("title", "") + " " + e.get("summary", "")).lower()
                if any(k in text for k in KEYWORDS):
                    add(e.get("title", ""), outlet_of(e), e.get("link", ""), re.sub("<[^>]+>", "", e.get("summary", "")))
        except Exception as ex:
            print("feed failed:", f, ex)
    try:
        r = requests.get(GDELT, params={"query": "Tigray OR TPLF OR Mekelle", "mode": "artlist", "format": "json",
                                         "timespan": "2d", "maxrecords": 50}, timeout=30)
        for a in r.json().get("articles", []):
            add(a.get("title", ""), a.get("domain", ""), a.get("url", ""))
    except Exception as ex:
        print("GDELT failed:", ex)
    return items[:MAX_ITEMS]

# ---- 3. ASK GEMINI TO STRUCTURE (it extracts; it does NOT grade) ---------
PROMPT = """Today is {today}. Below are numbered news items about the conflict in Tigray / northern Ethiopia.
Extract distinct real-world EVENTS (territorial control change, airstrike/drone strike, clash, diplomatic move,
humanitarian incident, claim by a party). Merge items describing the same event. Ignore opinion and background.
Return ONLY a JSON list. Each object:
 "key": short stable id like "mekelle-control-2026-10-04" (lowercase, hyphens; same event => same key)
 "place": one of {places} or "" if none fits
 "date": YYYY-MM-DD when the event happened
 "kind": control_change | strike | clash | diplomatic | humanitarian | claim | other
 "summary": one neutral sentence, attribute claims ("TPF says...") never state them as fact
 "attribution": "party" if the information comes only from a fighting party or its supporters (ENDF, TPLF, TPF, Fano, Eritrean govt, etc.), else "independent"
 "items": list of item numbers that support it
Items:
{items}"""

def extract(items):
    if not items:
        return []
    if not API_KEY:
        print("GEMINI_API_KEY is missing. Add it as a secret (see README)."); return []
    listing = "\n".join(f"{i}. [{x['outlet']}] {x['title']} - {x['summary']}" for i, x in enumerate(items))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": PROMPT.format(today=TODAY, places=", ".join(PLACES), items=listing)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    for attempt in range(3):                      # free tiers sometimes say "slow down" (429); wait and retry
        r = requests.post(url, headers={"x-goog-api-key": API_KEY}, json=body, timeout=120)
        if r.status_code in (429, 503):
            print("Busy or rate-limited, retrying..."); time.sleep(30 * (attempt + 1)); continue
        break
    if r.status_code != 200:
        print("Gemini error", r.status_code, r.text[:300]); return []
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        return json.loads(text)
    except Exception as ex:
        print("Could not read Gemini's answer:", ex); return []

# ---- 4. GRADE WITH SIMPLE, VISIBLE RULES ---------------------------------
def grade(ev):
    outlets = {s["outlet"].lower() for s in ev["sources"]}
    wires = {o for o in outlets if any(w in o for w in WIRES)}
    if len(wires) >= 2 and ev.get("attribution") != "party":
        return "CONFIRMED"
    if len(outlets) >= 2:
        return "REPORTED"      # several outlets, or a party claim that a few outlets repeat
    return "CLAIM"

def merge(db, new, items):
    for n in new:
        key = n.get("key")
        if not key: continue
        ev = db.get(key) or {"key": key, "sources": [], "manual": False}
        if ev.get("manual"): continue            # never overwrite hand-checked events
        place = n.get("place", "")
        ev.update({"place": place, "lat": PLACES.get(place, (None, None))[0], "lon": PLACES.get(place, (None, None))[1],
                   "date": n.get("date", TODAY), "kind": n.get("kind", "other"), "summary": n.get("summary", ""),
                   "attribution": n.get("attribution", "party"), "last_seen": TODAY})
        have = {s["url"] for s in ev["sources"]}
        for i in n.get("items", []):
            if isinstance(i, int) and 0 <= i < len(items) and items[i]["url"] not in have:
                s = items[i]; ev["sources"].append({"outlet": s["outlet"], "url": s["url"], "title": s["title"]})
        ev["grade"] = grade(ev)
        db[key] = ev

def main():
    db = {e["key"]: e for e in json.load(open(OUT))["events"]} if os.path.exists(OUT) else {}
    items = gather(); print("items gathered:", len(items))
    merge(db, extract(items), items)
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    events = [e for e in db.values() if e.get("manual") or e.get("last_seen", TODAY) >= cutoff]
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    json.dump({"updated": dt.datetime.utcnow().isoformat() + "Z", "events": events}, open(OUT, "w"), indent=1)
    print("events saved:", len(events))

if __name__ == "__main__":
    main()
