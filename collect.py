"""Tigray OSINT collector with language-aware translation, event extraction, and deterministic evidence grading."""
import os, json, re, datetime as dt, hashlib, time
from urllib.parse import urlparse
import feedparser, requests

OUT="data/events.json"; QUEUE="data/source_queue.json"; STATUS="data/status.json"; TODAY=dt.date.today().isoformat()
KEEP_DAYS=45; QUEUE_DAYS=2; MAX_ITEMS=100; SOCIAL_MAX=40; PROCESS_MAX_ITEMS=80
MODEL=os.environ.get("MODEL","gemini-2.5-flash-lite")
API_KEY=os.environ.get("GEMINI_API_KEY","")
RUN_MODE=os.environ.get("RUN_MODE","process")

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
        r=requests.get(GDELT,params={"query":"Tigray OR TPLF OR Mekelle","mode":"artlist",
                                     "format":"json","timespan":"2d","maxrecords":60},timeout=30)
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
                published=dt.datetime.fromtimestamp(p["created_utc"],dt.timezone.utc).isoformat() if p.get("created_utc") else ""
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

PROMPT="""You are structuring OSINT reports about Tigray and northern Ethiopia.
Today is {today}. First detect the language of each NEW source item. Only when the source text is Amharic (አማርኛ) or Tigrinya (ትግርኛ), translate it to neutral English for analysis. Do NOT translate English text. Preserve the original wording for every translated item and do not silently alter names, places, numbers, dates, or claims. If language detection is uncertain, do not translate; mark language as unknown. Then extract distinct real-world EVENTS from the numbered NEW source items.
Merge reports that clearly describe the same event. If a new report clearly describes an existing event below, reuse that existing event's key.
Do not invent facts. Ignore opinion/background.
A social-media post is a report/claim, not proof. Preserve attribution. Do not treat reposts or repeated wording as independent evidence.
Return only the requested JSON. Each event must contain:
key, place, date, kind, summary, attribution, items, translations.
kind must be control_change, strike, clash, diplomatic, humanitarian, claim, or other.
attribution must be party or independent.
Use only these map places: {places}
Use the source publication date if the event date is not explicit. Only assign a place when supported.
Summaries must be neutral and attribute disputed claims such as "TPF says...". For translations, include one object per translated source in translations with source_index, language ("am" or "ti"), original_text, and english_translation. For English sources, do not include a translation object.
EXISTING RECENT EVENTS:
{existing}
NEW SOURCE ITEMS:
{items}"""

def extract_with_gemini(items, existing=None):
    if not items or not API_KEY:
        if not API_KEY: print("GEMINI_API_KEY missing; using deterministic fallback.")
        return []
    listing="\n".join(
        f"{i}. [{x['source_type']}/{x['platform']}] [{x['outlet']}] {x['title']} | "
        f"{x['summary']} | published={x['published']} | url={x['url']}"
        for i,x in enumerate(items))
    schema={"type":"ARRAY","items":{"type":"OBJECT","properties":{
        "key":{"type":"STRING"},"place":{"type":"STRING"},"date":{"type":"STRING"},
        "kind":{"type":"STRING"},"summary":{"type":"STRING"},"attribution":{"type":"STRING"},
        "items":{"type":"ARRAY","items":{"type":"INTEGER"}},
        "translations":{"type":"ARRAY","items":{"type":"OBJECT","properties":{
            "source_index":{"type":"INTEGER"},"language":{"type":"STRING"},"original_text":{"type":"STRING"},"english_translation":{"type":"STRING"}},
            "required":["source_index","language","original_text","english_translation"]}}},
        "required":["key","place","date","kind","summary","attribution","items","translations"]}}
    body={"contents":[{"parts":[{"text":PROMPT.format(today=TODAY,places=", ".join(PLACES),existing="\n".join(f"- {e.get('key','')} | {e.get('date','')} | {e.get('place','')} | {e.get('summary','')}" for e in (existing or [])[:30]) or "(none)",items=listing)}]}],
          "generationConfig":{"responseMimeType":"application/json","responseSchema":schema,
                              "temperature":0.1,"maxOutputTokens":5000}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(3):
        try:
            r=requests.post(url,headers={"x-goog-api-key":API_KEY},json=body,timeout=120)
            if r.status_code in (429,503) and attempt<2:
                print("Gemini busy/rate-limited; retrying...")
                time.sleep(10*(attempt+1)); continue
            if r.status_code!=200:
                print("Gemini error",r.status_code,r.text[:300]); return []
            text=r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            data=json.loads(text)
            return data if isinstance(data,list) else []
        except Exception as ex:
            print("Gemini extraction failed:",ex)
            if attempt<2: time.sleep(5*(attempt+1))
    return []

def infer_date(item):
    value=item.get("published",""); m=re.search(r"(20\d{2})[-/]([01]\d)[-/]([0-3]\d)",value)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else TODAY

def infer_place(text):
    low=text.lower()
    for place in sorted(PLACES,key=len,reverse=True):
        if place.lower() in low: return place
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

def grade(sources,attribution="independent"):
    outlets={(s.get("outlet") or "").lower() for s in sources if s.get("outlet")}
    news={o for o in outlets if not o.startswith("r/")}
    wires={o for o in news if any(w in o for w in WIRES)}
    social=[s for s in sources if s.get("source_type")=="social"]
    if len(wires)>=2 and attribution!="party": return "CONFIRMED"
    if len(wires)>=1 and social and attribution!="party": return "CORROBORATED"
    if len(news)>=2: return "REPORTED"
    if len(sources)>=2: return "DEVELOPING"
    return "CLAIM"

def confidence(g): return {"CONFIRMED":90,"CORROBORATED":75,"REPORTED":65,"DEVELOPING":45,"CLAIM":25}.get(g,25)

def finalize_event(db,key,n,items):
    if not key or not isinstance(n,dict): return
    ev=db.get(key) or {"key":key,"sources":[],"manual":False}
    if ev.get("manual"): return
    place=n.get("place","") if n.get("place","") in PLACES else ""
    date=n.get("date","")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}",str(date)): date=TODAY
    ev.update({"place":place,"lat":PLACES.get(place,(None,None))[0],"lon":PLACES.get(place,(None,None))[1],
               "date":date,"kind":n.get("kind","other"),"summary":str(n.get("summary",""))[:500],
               "attribution":n.get("attribution","independent"),"last_seen":TODAY})
    if "translations" not in ev: ev["translations"]=[]
    for tr in n.get("translations",[]):
        if not isinstance(tr,dict) or tr.get("language") not in ("am","ti"): continue
        source_index=tr.get("source_index")
        if not isinstance(source_index,int) or not (0<=source_index<len(items)): continue
        source=items[source_index]
        record={"outlet":source["outlet"],"url":source["url"],"language":tr["language"],
                "original_text":str(tr.get("original_text",""))[:1500],"english_translation":str(tr.get("english_translation",""))[:1500]}
        if not record["original_text"] or not record["english_translation"]: continue
        if not any(x.get("url")==record["url"] for x in ev["translations"]): ev["translations"].append(record)
    have={s.get("url") for s in ev["sources"]}
    for i in n.get("items",[]):
        if isinstance(i,int) and 0<=i<len(items):
            s=items[i]
            if s["url"] not in have:
                ev["sources"].append({"outlet":s["outlet"],"url":s["url"],"title":s["title"],
                    "source_type":s["source_type"],"platform":s["platform"],"author":s.get("author",""),
                    "published":s.get("published","")}); have.add(s["url"])
    ev["grade"]=grade(ev["sources"],ev.get("attribution","independent"))
    ev["confidence"]=confidence(ev["grade"])
    ev["source_count"]=len(ev["sources"])
    ev["social_source_count"]=sum(s.get("source_type")=="social" for s in ev["sources"])
    ev["news_source_count"]=sum(s.get("source_type")=="news" for s in ev["sources"])
    db[key]=ev

def deterministic_fallback(items):
    db={}
    for i,item in enumerate(items):
        text=item["title"]+" "+item.get("summary",""); place=infer_place(text); date=infer_date(item)
        key=event_key(item,place,date)
        finalize_event(db,key,{"place":place,"date":date,"kind":infer_kind(text),
            "summary":item["title"],"attribution":"party" if item["source_type"]=="social" else "independent",
            "items":[i]},items)
    return db

def load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path,encoding="utf-8") as f: return json.load(f)
    except Exception as ex:
        print("Could not read",path,ex); return default

def save_status():
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    with open(STATUS,"w",encoding="utf-8") as f: json.dump({"last_checked":now},f,indent=1,ensure_ascii=False)
    print("last source check:",now)

def save_queue(items):
    queue=load_json(QUEUE, [])
    urls={x.get("url") for x in queue}
    for item in items:
        if item.get("url") and item["url"] not in urls:
            item=dict(item); item["processed"]=False
            queue.append(item); urls.add(item["url"])
    queue=queue[-500:]
    with open(QUEUE,"w",encoding="utf-8") as f: json.dump(queue,f,indent=1,ensure_ascii=False)
    print("queue saved:",len(queue),"unprocessed:",sum(not x.get("processed") for x in queue))

def process_queue():
    queue=load_json(QUEUE, [])
    pending=[x for x in queue if not x.get("processed")][:PROCESS_MAX_ITEMS]
    if not pending:
        print("No new source items; Gemini skipped."); return
    data=load_json(OUT, {"events":[]})
    db={e["key"]:e for e in data.get("events",[]) if e.get("key")}
    candidates=extract_with_gemini(pending,list(db.values()))
    if not candidates:
        print("Gemini did not return events; queue remains for retry."); return
    for n in candidates:
        if isinstance(n,dict):
            key=str(n.get("key","")).strip()
            if key: finalize_event(db,key,n,pending)
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    for item in pending:
        item["processed"]=True; item["processed_at"]=now
    cutoff=(dt.date.today()-dt.timedelta(days=KEEP_DAYS)).isoformat()
    db={k:v for k,v in db.items() if v.get("manual") or v.get("last_seen",TODAY)>=cutoff}
    events=sorted(db.values(),key=lambda e:(e.get("date",""),e.get("last_seen","")),reverse=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump({"updated":now,"events":events},f,indent=1,ensure_ascii=False)
    with open(QUEUE,"w",encoding="utf-8") as f: json.dump(queue,f,indent=1,ensure_ascii=False)
    print("Gemini events processed:",len(candidates),"events saved:",len(events))

def main():
    if RUN_MODE=="collect":
        save_queue(gather())
        save_status()
    elif RUN_MODE=="process":
        process_queue()
    else:
        raise SystemExit(f"Unknown RUN_MODE: {RUN_MODE}")

if __name__=="__main__": main()
