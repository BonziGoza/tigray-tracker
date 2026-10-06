"""Tigray OSINT collector: news + optional X/Reddit social sources."""
import os, json, re, datetime as dt, time
from urllib.parse import urlparse
import feedparser, requests

MODEL=os.environ.get("MODEL","gemini-flash-latest")
GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY","")
OUT="data/events.json"; TODAY=dt.date.today().isoformat()
KEEP_DAYS=45; MAX_ITEMS=100; SOCIAL_MAX=40

FEEDS=[
 "https://news.google.com/rss/search?q=Tigray+when:2d&hl=en-US&gl=US&ceid=US:en",
 "https://news.google.com/rss/search?q=Mekelle+OR+TPLF+OR+Afar+OR+Eritrea+Ethiopia+when:2d&hl=en-US&gl=US&ceid=US:en",
 "https://www.aljazeera.com/xml/rss/all.xml"]
GDELT="https://api.gdeltproject.org/api/v2/doc/doc"
KEYWORDS=["tigray","tplf","mekelle","mekele","eritrea","afar","amhara","fano","abiy","ethiopia"]
WIRES=["reuters","associated press","ap news","apnews","afp","al jazeera","bbc","france 24","dw","the guardian","new york times"]
PLACES={"Mekelle":(13.50,39.47),"Alamata":(12.42,39.55),"Shire":(14.10,38.28),"Axum":(14.13,38.72),
"Adwa":(14.17,38.90),"Adigrat":(14.28,39.46),"Abala":(13.38,39.99),"Erebti":(13.30,40.12),
"Megale":(13.00,40.35),"Semera":(11.79,41.00),"Kobo":(12.15,39.63),"Sekota":(12.63,39.03),
"Lalibela":(12.03,39.04),"Dessie":(11.13,39.63),"Woldia":(11.83,39.60),"Addis Ababa":(9.03,38.74),
"Asmara":(15.34,38.93),"Bahir Dar":(11.59,37.39),"Gondar":(12.60,37.47),"Humera":(14.30,36.60),
"Zalambessa":(14.52,39.55)}

def clean_html(v): return re.sub(r"<[^>]+>"," ",v or "").strip()

def add_item(items,seen,title,outlet,url,summary="",source_type="news",platform="news",author="",published=""):
    title=(title or "").strip(); url=(url or "").strip()
    if not title or not url or url in seen: return
    seen.add(url)
    items.append({"title":title[:300],"outlet":(outlet or platform)[:120],"url":url,
                  "summary":clean_html(summary)[:600],"source_type":source_type,"platform":platform,
                  "author":author[:120],"published":published})

def outlet_of(e):
    src=e.get("source")
    return src["title"] if src and src.get("title") else urlparse(e.get("link","")).netloc.replace("www.","")

def gather_news():
    items=[]; seen=set()
    for feed_url in FEEDS:
        try:
            for e in feedparser.parse(feed_url).entries[:50]:
                text=(e.get("title","")+" "+e.get("summary","")).lower()
                if any(k in text for k in KEYWORDS):
                    add_item(items,seen,e.get("title",""),outlet_of(e),e.get("link",""),e.get("summary",""),
                             "news","rss","",e.get("published",""))
        except Exception as ex: print("feed failed:",feed_url,ex)
    try:
        r=requests.get(GDELT,params={"query":"Tigray OR TPLF OR Mekelle","mode":"artlist","format":"json",
                                     "timespan":"2d","maxrecords":60},timeout=30)
        r.raise_for_status()
        for a in r.json().get("articles",[]):
            add_item(items,seen,a.get("title",""),a.get("domain",""),a.get("url",""),a.get("seendate",""),
                     "news","gdelt","",a.get("seendate",""))
    except Exception as ex: print("GDELT failed:",ex)
    return items

def gather_reddit():
    cid=os.environ.get("REDDIT_CLIENT_ID",""); secret=os.environ.get("REDDIT_CLIENT_SECRET","")
    if not cid or not secret:
        print("Reddit collector disabled: credentials not configured."); return []
    items=[]; seen=set(); ua=os.environ.get("REDDIT_USER_AGENT","TigrayOSINTTracker/1.0 by BonziGoza")
    try:
        tr=requests.post("https://www.reddit.com/api/v1/access_token",auth=(cid,secret),
                         data={"grant_type":"client_credentials"},headers={"User-Agent":ua},timeout=30)
        tr.raise_for_status(); token=tr.json()["access_token"]
        headers={"Authorization":f"bearer {token}","User-Agent":ua}
        for query in ["Tigray","Mekelle","TPLF","Ethiopia Tigray"]:
            r=requests.get("https://oauth.reddit.com/search",
                params={"q":query,"sort":"new","t":"day","limit":25,"restrict_sr":"false","type":"link,self"},
                headers=headers,timeout=30)
            if r.status_code==429: print("Reddit rate limited; stopping."); break
            r.raise_for_status()
            for child in r.json().get("data",{}).get("children",[]):
                p=child.get("data",{}); permalink=p.get("permalink","")
                url="https://www.reddit.com"+permalink if permalink else p.get("url","")
                published=""
                if p.get("created_utc"):
                    published=dt.datetime.fromtimestamp(p["created_utc"],dt.timezone.utc).isoformat()
                add_item(items,seen,p.get("title",""),f"r/{p.get('subreddit','')}",url,p.get("selftext",""),
                         "social","reddit",p.get("author","") or "[deleted]",published)
    except Exception as ex: print("Reddit failed:",ex)
    return items[:SOCIAL_MAX]

def gather_x():
    bearer=os.environ.get("X_BEARER_TOKEN","")
    if not bearer: print("X collector disabled: X_BEARER_TOKEN not configured."); return []
    items=[]; seen=set()
    queries=['(Tigray OR Mekelle OR TPLF OR "Tigray region") -is:retweet lang:en',
             '(Ethiopia OR Eritrea) (Tigray OR Mekelle OR TPLF) -is:retweet lang:en']
    try:
        for query in queries:
            r=requests.get("https://api.x.com/2/tweets/search/recent",
                params={"query":query,"max_results":50,"tweet.fields":"created_at,author_id,lang",
                        "expansions":"author_id","user.fields":"username,name,verified"},
                headers={"Authorization":f"Bearer {bearer}"},timeout=30)
            if r.status_code==429: print("X rate limited; stopping."); break
            r.raise_for_status(); payload=r.json()
            users={u["id"]:u for u in payload.get("includes",{}).get("users",[])}
            for p in payload.get("data",[]):
                user=users.get(p.get("author_id"),{}); username=user.get("username","")
                url=f"https://x.com/{username}/status/{p['id']}" if username else f"https://x.com/i/web/status/{p['id']}"
                add_item(items,seen,p.get("text","")[:180],f"@{username}" if username else "X",url,p.get("text",""),
                         "social","x",username,p.get("created_at",""))
    except Exception as ex: print("X failed:",ex)
    return items[:SOCIAL_MAX]

def gather():
    items=gather_news()+gather_reddit()+gather_x()
    items=[x for x in items if x["source_type"]=="news" or any(k in (x["title"]+" "+x["summary"]).lower() for k in KEYWORDS)]
    print("items gathered:",len(items),"news:",sum(x["source_type"]=="news" for x in items),
          "social:",sum(x["source_type"]=="social" for x in items))
    return items[:MAX_ITEMS]

PROMPT="""Today is {today}. Below are numbered information items about the conflict in Tigray / northern Ethiopia.
Sources may be professional news, RSS/GDELT, Reddit, or X.
Extract distinct real-world EVENTS. Merge items describing the same event. Ignore opinion/background.
A social-media post is a report/claim, not proof. Preserve attribution. Do not treat reposts as independent evidence.
Return ONLY a JSON list. Each object:
"key": short stable id such as "mekelle-explosions-2026-10-06"
"place": one of {places} or ""
"date": YYYY-MM-DD
"kind": control_change | strike | clash | diplomatic | humanitarian | claim | other
"summary": one neutral sentence with attribution where appropriate
"attribution": "party" | "social" | "independent"
"items": list of supporting item numbers
Items:
{items}"""

def extract(items):
    if not items or not GEMINI_API_KEY:
        if not GEMINI_API_KEY: print("GEMINI_API_KEY missing; extraction skipped.")
        return []
    listing="\n".join(f"{i}. [{x['source_type']}/{x['platform']}] [{x['outlet']}] {x['title']} - {x['summary']}"
                      for i,x in enumerate(items))
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body={"contents":[{"parts":[{"text":PROMPT.format(today=TODAY,places=", ".join(PLACES),items=listing)}]}],
          "generationConfig":{"responseMimeType":"application/json","temperature":0.1}}
    for attempt in range(3):
        r=requests.post(url,headers={"x-goog-api-key":GEMINI_API_KEY},json=body,timeout=120)
        if r.status_code in (429,503): time.sleep(30*(attempt+1)); continue
        break
    if r.status_code!=200: print("Gemini error",r.status_code,r.text[:500]); return []
    try:
        text=r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text=text.replace(chr(96),"").strip()
        return json.loads(text)
    except Exception as ex: print("Could not parse Gemini:",ex); return []

def normalize_sources(sources):
    out=[]
    for source in sources or []:
        s=dict(source); s.setdefault("source_type","news"); s.setdefault("platform","news")
        s.setdefault("author",""); s.setdefault("published",""); out.append(s)
    return out

def grade(ev):
    sources=normalize_sources(ev.get("sources",[]))
    outlets={(s.get("outlet") or "").lower() for s in sources if s.get("outlet")}
    news={o for o in outlets if not o.startswith("@") and not o.startswith("r/")}
    wires={o for o in news if any(w in o for w in WIRES)}
    social={s.get("platform","") for s in sources if s.get("source_type")=="social"}
    if len(wires)>=2 and ev.get("attribution")=="independent": return "CONFIRMED"
    if len(wires)>=1 and social and ev.get("attribution")!="party": return "CORROBORATED"
    if len(news)>=2: return "REPORTED"
    if len(sources)>=2 or len(social)>=2: return "DEVELOPING"
    return "CLAIM"

def confidence(grade):
    return {"CONFIRMED":90,"CORROBORATED":75,"REPORTED":65,"DEVELOPING":45,"CLAIM":25}.get(grade,25)

def merge(db,new,items):
    for n in new:
        key=n.get("key")
        if not key: continue
        ev=db.get(key) or {"key":key,"sources":[],"manual":False}
        if ev.get("manual"): continue
        place=n.get("place",""); lat,lon=PLACES.get(place,(None,None))
        ev.update({"place":place,"lat":lat,"lon":lon,"date":n.get("date",TODAY),
                   "kind":n.get("kind","other"),"summary":n.get("summary",""),
                   "attribution":n.get("attribution","party"),"last_seen":TODAY})
        ev["sources"]=normalize_sources(ev.get("sources")); have={s.get("url") for s in ev["sources"]}
        for i in n.get("items",[]):
            if isinstance(i,int) and 0<=i<len(items) and items[i]["url"] not in have:
                x=items[i]
                ev["sources"].append({"outlet":x["outlet"],"url":x["url"],"title":x["title"],
                    "source_type":x["source_type"],"platform":x["platform"],"author":x.get("author",""),
                    "published":x.get("published","")})
                have.add(x["url"])
        ev["grade"]=grade(ev); ev["confidence"]=confidence(ev["grade"])
        ev["source_count"]=len(ev["sources"])
        ev["social_source_count"]=sum(s.get("source_type")=="social" for s in ev["sources"])
        ev["news_source_count"]=sum(s.get("source_type")=="news" for s in ev["sources"])
        db[key]=ev

def main():
    if os.path.exists(OUT):
        with open(OUT,encoding="utf-8") as f: db={e["key"]:e for e in json.load(f).get("events",[])}
    else: db={}
    items=gather(); new=extract(items); print("candidate events:",len(new)); merge(db,new,items)
    cutoff=(dt.date.today()-dt.timedelta(days=KEEP_DAYS)).isoformat()
    events=[e for e in db.values() if e.get("manual") or e.get("last_seen",TODAY)>=cutoff]
    events.sort(key=lambda e:(e.get("date",""),e.get("last_seen","")),reverse=True)
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump({"updated":dt.datetime.now(dt.timezone.utc).isoformat(),"events":events},f,indent=1,ensure_ascii=False)
    print("events saved:",len(events))

if __name__=="__main__": main()
