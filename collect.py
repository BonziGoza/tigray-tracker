"""Tigray OSINT collector using free public news/RSS/GDELT sources and optional Reddit API."""
import os, json, re, datetime as dt, hashlib
from urllib.parse import urlparse
import feedparser, requests

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

def gather():
    items=gather_news()+gather_reddit()
    items=[x for x in items if x["source_type"]=="news" or any(k in (x["title"]+" "+x["summary"]).lower() for k in KEYWORDS)]
    print("items gathered:",len(items),"news:",sum(x["source_type"]=="news" for x in items),
          "social:",sum(x["source_type"]=="social" for x in items))
    return items[:MAX_ITEMS]

def infer_date(item):
    value=item.get("published","")
    if value:
        m=re.search(r"(20\d{2})[-/]([01]\d)[-/]([0-3]\d)",value)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return TODAY

def infer_place(text):
    low=text.lower()
    for place in sorted(PLACES,key=len,reverse=True):
        if place.lower() in low:
            return place
    return ""

def infer_kind(text):
    low=text.lower()
    if any(x in low for x in ["airstrike","air strike","bombed","bombing","drone strike","missile","strike"]): return "strike"
    if any(x in low for x in ["clash","fighting","battle","combat","killed","attack","ambush"]): return "clash"
    if any(x in low for x in ["agreement","talks","meeting","negotiat","diplomatic","peace"]): return "diplomatic"
    if any(x in low for x in ["displaced","famine","food","aid","humanitarian","refugee"]): return "humanitarian"
    if any(x in low for x in ["control","captured","seized","occupied","withdrew","withdrawal"]): return "control_change"
    return "claim" if any(x in low for x in ["claim","alleged","reportedly","unconfirmed"]) else "other"

def event_key(item,place,date):
    text=re.sub(r"[^a-z0-9 ]"," ",(item["title"]+" "+place).lower())
    words=[w for w in text.split() if len(w)>2][:12]
    return f"{place.lower().replace(' ','-') or 'unknown'}-{date}-"+hashlib.sha1(" ".join(words).encode()).hexdigest()[:8]

def grade(sources):
    outlets={(s.get("outlet") or "").lower() for s in sources if s.get("outlet")}
    news={o for o in outlets if not o.startswith("@") and not o.startswith("r/")}
    wires={o for o in news if any(w in o for w in WIRES)}
    social=[s for s in sources if s.get("source_type")=="social"]
    if len(wires)>=2: return "CONFIRMED"
    if len(wires)>=1 and social: return "CORROBORATED"
    if len(news)>=2: return "REPORTED"
    if len(sources)>=2: return "DEVELOPING"
    return "CLAIM"

def confidence(g): return {"CONFIRMED":90,"CORROBORATED":75,"REPORTED":65,"DEVELOPING":45,"CLAIM":25}.get(g,25)

def build_events(items):
    db={}
    for item in items:
        text=item["title"]+" "+item.get("summary","")
        place=infer_place(text); date=infer_date(item); key=event_key(item,place,date)
        ev=db.get(key)
        if not ev:
            ev={"key":key,"place":place,"lat":PLACES.get(place,(None,None))[0],
                "lon":PLACES.get(place,(None,None))[1],"date":date,
                "kind":infer_kind(text),"summary":item["title"],
                "attribution":"social" if item["source_type"]=="social" else "independent",
                "sources":[],"manual":False,"last_seen":TODAY}
            db[key]=ev
        if not any(s.get("url")==item["url"] for s in ev["sources"]):
            ev["sources"].append({"outlet":item["outlet"],"url":item["url"],"title":item["title"],
                "source_type":item["source_type"],"platform":item["platform"],
                "author":item.get("author",""),"published":item.get("published","")})
            ev["last_seen"]=TODAY
        ev["grade"]=grade(ev["sources"]); ev["confidence"]=confidence(ev["grade"])
        ev["source_count"]=len(ev["sources"])
        ev["social_source_count"]=sum(s.get("source_type")=="social" for s in ev["sources"])
        ev["news_source_count"]=sum(s.get("source_type")=="news" for s in ev["sources"])
    return db

def main():
    if os.path.exists(OUT):
        with open(OUT,encoding="utf-8") as f: old={e["key"]:e for e in json.load(f).get("events",[])}
    else: old={}
    fresh=build_events(gather())
    db={k:v for k,v in old.items() if v.get("manual") or v.get("last_seen",TODAY)>=(
        dt.date.today()-dt.timedelta(days=KEEP_DAYS)).isoformat()}
    db.update(fresh)
    events=list(db.values())
    events.sort(key=lambda e:(e.get("date",""),e.get("last_seen","")),reverse=True)
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump({"updated":dt.datetime.now(dt.timezone.utc).isoformat(),"events":events},f,indent=1,ensure_ascii=False)
    print("events saved:",len(events))

if __name__=="__main__": main()
