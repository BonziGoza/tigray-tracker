"""Tigray OSINT collector with language-aware translation, event extraction, and deterministic evidence grading."""
import os, json, re, datetime as dt, hashlib, time
from urllib.parse import urlparse
import feedparser, requests

OUT="data/events.json"; QUEUE="data/source_queue.json"; STATUS="data/status.json"; TODAY=dt.date.today().isoformat()
KEEP_DAYS=45; QUEUE_DAYS=2; MAX_ITEMS=100; SOCIAL_MAX=40; PROCESS_MAX_ITEMS=180; PROCESS_BATCH_SIZE=30
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
REGIONS={
    "Northern Tigray":"Northern Tigray","Western Tigray":"Western Tigray",
    "Eastern Tigray":"Eastern Tigray","Southern Tigray":"Southern Tigray",
    "Central Tigray":"Central Tigray","Northwestern Tigray":"Northwestern Tigray",
    "Northeastern Tigray":"Northeastern Tigray"
}

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

TELEGRAM_CHANNELS=[
    "Tigrai_Ttv",
    "axumawianmedia",
    "tigrignafana",
    "tikvahethiopiA",
    "tikvahethiopiatigrigna",
    "ASCENTIG",
]

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
    # Telegram has its own relevance filter. Do not apply the Latin-keyword
    # filter here: it can discard valid Amharic/Tigrinya social posts.
    print("items gathered:",len(items),"news:",sum(x["source_type"]=="news" for x in items),
          "social:",sum(x["source_type"]=="social" for x in items))
    return items[:MAX_ITEMS]

PROMPT="""You are structuring OSINT reports about Tigray and northern Ethiopia.
Today is {today}. First detect the language of each NEW source item. Only when the source text is Amharic (አማርኛ) or Tigrinya (ትግርኛ), translate it to neutral English for analysis. Do NOT translate English text. Preserve the original wording for every translated item and do not silently alter names, places, numbers, dates, or claims. If language detection is uncertain, do not translate; mark language as unknown. Then extract distinct real-world EVENTS from the numbered NEW source items.
Merge reports that clearly describe the same event. If a new report clearly describes an existing event below, reuse that existing event's key.
Do not invent facts. Ignore only clearly irrelevant content.
Do not silently drop a relevant news or social report: if it describes a real development, make or attach it to an event. Political, diplomatic, humanitarian, security, and control developments are still events even when they are not combat.
A social-media post is a report/claim, not proof. Preserve attribution. Do not treat reposts or repeated wording as independent evidence.
Every relevant source item should appear in at least one event's items array. If an item is truly irrelevant, put its index in ignored_items with a brief reason.
Return only the requested JSON. Each event must contain:
key, place, region, date, kind, summary, attribution, items, translations.
kind must be control_change, strike, clash, diplomatic, humanitarian, claim, or other.
attribution must be party or independent.
Use only these exact map places: {places}
Regional areas allowed: Northern Tigray, Western Tigray, Eastern Tigray, Southern Tigray, Central Tigray, Northwestern Tigray, Northeastern Tigray.
LOCATION RULES: Only report a specific place when the source explicitly names that place. Never infer a town/city from a region or from the general topic. If the source explicitly says "Northern Tigray" or another regional area, set region to that region and leave place empty. If no geographic area is stated, leave both place and region empty. Do not use "unknown", "unconfirmed", "unclear", or similar text as a location.
Use the source publication date if the event date is not explicit. Only assign a place or region when supported by the source.
Summaries must be neutral and attribute disputed claims such as "TPF says...". For translations, include one object per translated source in translations with source_index, language ("am" or "ti"), original_text, and english_translation. For English sources, do not include a translation object.
EXISTING RECENT EVENTS:
{existing}
NEW SOURCE ITEMS:
{items}"""

def extract_with_gemini(items, existing=None):
    if not items or not API_KEY:
        if not API_KEY: print("GEMINI_API_KEY missing; using deterministic fallback.")
        return deterministic_fallback(items)
    listing="\n".join(
        f"{i}. [{x['source_type']}/{x['platform']}] [{x['outlet']}] {x['title']} | "
        f"{x['summary']} | published={x['published']} | url={x['url']}"
        for i,x in enumerate(items))
    schema={"type":"ARRAY","items":{"type":"OBJECT","properties":{
        "key":{"type":"STRING"},"place":{"type":"STRING"},"region":{"type":"STRING"},"date":{"type":"STRING"},
        "kind":{"type":"STRING"},"summary":{"type":"STRING"},"attribution":{"type":"STRING"},
        "items":{"type":"ARRAY","items":{"type":"INTEGER"}},
        "ignored_items":{"type":"ARRAY","items":{"type":"INTEGER"}},
        "translations":{"type":"ARRAY","items":{"type":"OBJECT","properties":{
            "source_index":{"type":"INTEGER"},"language":{"type":"STRING"},"original_text":{"type":"STRING"},"english_translation":{"type":"STRING"}},
            "required":["source_index","language","original_text","english_translation"]}}},
        "required":["key","place","region","date","kind","summary","attribution","items","ignored_items","translations"]}}
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
                print("Gemini error",r.status_code,r.text[:300]); return deterministic_fallback(items)
            text=r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            data=json.loads(text)
            return data if isinstance(data,list) and data else deterministic_fallback(items)
        except Exception as ex:
            print("Gemini extraction failed:",ex)
            if attempt<2:
                time.sleep(5*(attempt+1))
                continue
            return deterministic_fallback(items)
    return deterministic_fallback(items)

def contains_ethio_script(text):
    return bool(re.search(r"[\u1200-\u137F]", str(text or "")))

def translate_social_items(items):
    """Translate Amharic/Tigrinya social posts to neutral English when Gemini is available."""
    if not API_KEY: return {}
    targets=[(i,x) for i,x in enumerate(items) if contains_ethio_script(x.get("title","")) or contains_ethio_script(x.get("summary",""))]
    if not targets: return {}
    listing="\n".join(f'{i}. {x["title"]} | {x.get("summary","")}' for i,x in targets)
    prompt=f"""Translate the following source items for an English-language OSINT tracker. Today is {TODAY}.\nDetect the language. Translate ONLY Amharic or Tigrinya into neutral, literal English. If language is uncertain, return language=unknown and do not invent a translation. If an item is already English, return its original text unchanged. Preserve names, places, numbers, dates, and uncertainty. Do not add facts. Return JSON only as an array of objects with source_index, language (am/ti/unknown/en), original_text, english_translation. Every source index must appear exactly once.\nITEMS:\n{listing}"""
    schema={"type":"ARRAY","items":{"type":"OBJECT","properties":{"source_index":{"type":"INTEGER"},"language":{"type":"STRING"},"original_text":{"type":"STRING"},"english_translation":{"type":"STRING"}},"required":["source_index","language","original_text","english_translation"]}}
    body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema,"temperature":0.1,"maxOutputTokens":6000}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    try:
        r=requests.post(url,headers={"x-goog-api-key":API_KEY},json=body,timeout=120)
        if r.status_code!=200:
            print("Gemini translation error",r.status_code,r.text[:300]); return {}
        data=json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
        return {int(x["source_index"]):x for x in data if isinstance(x,dict) and str(x.get("language")) in ("am","ti") and x.get("english_translation")}
    except Exception as ex:
        print("Gemini translation failed:",ex); return {}

def infer_date(item):
    value=item.get("published",""); m=re.search(r"(20\d{2})[-/]([01]\d)[-/]([0-3]\d)",value)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else TODAY

def infer_place(text):
    low=str(text or "").lower()
    for place in sorted(PLACES,key=len,reverse=True):
        if place.lower() in low: return place
    return ""

def infer_region(text):
    low=str(text or "").lower()
    for region in sorted(REGIONS,key=len,reverse=True):
        if region.lower() in low: return region
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

def source_quality(source):
    """Return a small quality score used for evidence grading, not truth."""
    if source.get("source_type") == "social":
        return 1
    outlet=(source.get("outlet") or "").lower().strip()
    if any(w in outlet for w in WIRES):
        return 3
    if any(x in outlet for x in [
        "africanews","addis standard","allafrica","semafor","guardian",
        "france 24","dw","bbc","voa","al-monitor","foreign policy"
    ]):
        return 2
    return 1

def independent_sources(sources):
    """Collapse obvious reposts before counting independent evidence."""
    seen_fingerprints=set()
    out=[]
    for source in sources:
        fp=source.get("repost_of_fingerprint") or source.get("fingerprint")
        if fp and fp in seen_fingerprints:
            continue
        if fp: seen_fingerprints.add(fp)
        out.append(source)
    return out

def evidence_score(sources,attribution="independent"):
    """Continuous 0-100 evidence score; this is not a probability of truth."""
    src=independent_sources(sources)
    news={}
    for source in src:
        if source.get("source_type")=="news" and source.get("outlet"):
            news[source.get("outlet","").lower().strip()]=source
    high=[x for x in news.values() if source_quality(x)>=3]
    professional=[x for x in news.values() if source_quality(x)>=2]
    social=[x for x in src if x.get("source_type")=="social"]

    # Starting evidence reflects source quality. Corroboration then raises the
    # score. A single social post can never look equivalent to a professional
    # news report, and copied/reposted sources are already collapsed above.
    if high:
        score=70
        score += min(20, 12*(len(high)-1))
    elif professional:
        score=58
        score += min(24, 10*(len(professional)-1))
    elif news:
        score=42
        score += min(24, 8*(len(news)-1))
    elif social:
        score=24
        score += min(20, 8*(len(social)-1))
    else:
        score=15

    # Cross-type corroboration is useful but weaker than an independent
    # professional news source.
    if high and social:
        score += min(8, 4*len(social))
    elif professional and social:
        score += min(6, 3*len(social))

    if attribution=="party":
        score-=8
    return max(10,min(98,int(round(score))))

def grade(sources,attribution="independent"):
    src=independent_sources(sources)
    news={}
    for source in src:
        if source.get("source_type")=="news" and source.get("outlet"):
            news[source.get("outlet","").lower().strip()]=source
    high=[x for x in news.values() if source_quality(x)>=3]
    professional=[x for x in news.values() if source_quality(x)>=2]
    social=[x for x in src if x.get("source_type")=="social"]

    # Grade is categorical and deliberately stricter than the numeric score.
    # "Confirmed" requires substantial independent professional corroboration.
    if len(high)>=3 or (len(high)>=2 and len(professional)>=3):
        return "CONFIRMED"
    if len(high)>=2 or len(professional)>=2:
        return "CORROBORATED"
    if news:
        return "REPORTED"
    if len(social)>=2:
        return "DEVELOPING"
    return "CLAIM"

def confidence(sources,attribution="independent"):
    return evidence_score(sources,attribution)

def finalize_event(db,key,n,items):
    if not key or not isinstance(n,dict): return
    ev=db.get(key) or {"key":key,"sources":[],"manual":False}
    if ev.get("manual"): return
    place=n.get("place","") if n.get("place","") in PLACES else ""
    region=n.get("region","") if n.get("region","") in REGIONS else ""
    if place: region=""
    date=n.get("date","")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}",str(date)): date=TODAY
    ev.update({"place":place,"region":region,"lat":PLACES.get(place,(None,None))[0],"lon":PLACES.get(place,(None,None))[1],
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
                ev["sources"].append({"outlet":s["outlet"],"url":s["url"],"title":s.get("original_title",s["title"]),
                    "source_type":s["source_type"],"platform":s["platform"],"author":s.get("author",""),
                    "published":s.get("published",""),"fingerprint":s.get("fingerprint",""),
                    "repost_of_fingerprint":s.get("repost_of_fingerprint","")}); have.add(s["url"])
    if contains_ethio_script(ev.get("summary","")):
        translated_for_event=[x.get("english_translation") for x in ev.get("translations",[]) if x.get("english_translation")]
        if translated_for_event:
            ev["summary"]=translated_for_event[0][:500]
    ev["grade"]=grade(ev["sources"],ev.get("attribution","independent"))
    ev["confidence"]=confidence(ev["sources"],ev.get("attribution","independent"))
    ev["source_count"]=len(independent_sources(ev["sources"]))
    ev["social_source_count"]=sum(s.get("source_type")=="social" for s in ev["sources"])
    ev["news_source_count"]=sum(s.get("source_type")=="news" for s in ev["sources"])
    db[key]=ev

def deterministic_fallback(items):
    """Conservative fallback that groups obvious duplicates and keeps every source."""
    groups=[]
    for i,item in enumerate(items):
        text=(item.get("title","")+" "+item.get("summary","")).strip()
        place=infer_place(text)
        region="" if place else infer_region(text)
        date=infer_date(item)
        kind=infer_kind(text)
        normalized=re.sub(r"[^a-z0-9 ]"," ",text.lower())
        words={w for w in normalized.split() if len(w)>3}
        best=None; best_score=0
        for g in groups:
            if g["place"] != place or g["region"] != region or g["date"] != date: continue
            overlap=len(words & g["words"])/max(1,len(words | g["words"]))
            if overlap >= 0.45 and overlap > best_score:
                best_score=overlap; best=g
        if best:
            best["items"].append(i); best["words"] |= words
        else:
            groups.append({
                "place":place,"region":region,"date":date,"kind":kind,"words":words,
                "items":[i],
                "key":event_key(item,place or region,date),
                "summary":item["title"][:500],
                "attribution":"party" if item["source_type"]=="social" else "independent",
                "translations":[]
            })
    return [{k:v for k,v in g.items() if k!="words"} for g in groups]

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

def published_sort_key(item):
    """Normalize mixed RSS and ISO timestamps so newest sources are processed first."""
    value=str(item.get("published","") or "").strip()
    if not value: return 0.0
    try:
        return dt.datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
    except ValueError:
        try:
            return dt.datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            return 0.0

def process_queue():
    queue=load_json(QUEUE, [])
    pending_all=sorted((x for x in queue if not x.get("processed")), key=published_sort_key, reverse=True)
    if not pending_all:
        print("No new source items; Gemini skipped."); return

    # Work in bounded batches so a large Telegram burst cannot crowd out news,
    # and so one model response cannot accidentally merge unrelated stories.
    pending_all=pending_all[:PROCESS_MAX_ITEMS]
    data=load_json(OUT, {"events":[]})
    db={e["key"]:e for e in data.get("events",[]) if e.get("key")}
    processed_count=0
    batch_count=0

    for offset in range(0,len(pending_all),PROCESS_BATCH_SIZE):
        batch=pending_all[offset:offset+PROCESS_BATCH_SIZE]
        if not batch: continue
        batch_count+=1

        # Translate first so Gemini sees English text for Amharic/Tigrinya social
        # sources while we still preserve the original source text.
        translations=translate_social_items(batch)
        analysis_items=[]
        for i,item in enumerate(batch):
            x=dict(item)
            x["original_title"]=item.get("title","")
            tr=translations.get(i)
            if tr and tr.get("english_translation"):
                x["title"]=tr["english_translation"][:300]
                x["summary"]=tr["english_translation"][:600]
                x["detected_language"]=tr.get("language")
            analysis_items.append(x)

        candidates=extract_with_gemini(analysis_items,list(db.values()))
        if not candidates:
            print("No candidates returned for batch; leaving batch unprocessed.")
            continue

        covered=set()
        valid_candidates=[]
        for n in candidates:
            if not isinstance(n,dict): continue
            indices=[i for i in n.get("items",[]) if isinstance(i,int) and 0<=i<len(batch)]
            if not indices:
                continue
            n["items"]=indices
            covered.update(indices)
            if translations:
                n["translations"]=(n.get("translations") or [])+[
                    dict(v,source_index=k) for k,v in translations.items() if k in indices
                ]
            valid_candidates.append(n)

        # Never let a model omission permanently lose a source. Create a
        # conservative fallback event for every uncovered source.
        uncovered=[i for i in range(len(batch)) if i not in covered]
        if uncovered:
            print("Uncovered source items; deterministic fallback:",len(uncovered))
            for n in deterministic_fallback([analysis_items[i] for i in uncovered]):
                remapped=[]
                for local_i in n.get("items",[]):
                    if isinstance(local_i,int) and 0<=local_i<len(uncovered):
                        remapped.append(uncovered[local_i])
                n["items"]=remapped
                valid_candidates.append(n)

        for n in valid_candidates:
            key=str(n.get("key","")).strip()
            if key:
                finalize_event(db,key,n,analysis_items)

        now=dt.datetime.now(dt.timezone.utc).isoformat()
        batch_urls={x.get("url") for x in batch}
        for item in queue:
            if item.get("url") in batch_urls and not item.get("processed"):
                item["processed"]=True
                item["processed_at"]=now
        processed_count+=len(batch)

    cutoff=(dt.date.today()-dt.timedelta(days=KEEP_DAYS)).isoformat()
    db={k:v for k,v in db.items() if v.get("manual") or v.get("last_seen",TODAY)>=cutoff}
    events=sorted(db.values(),key=lambda e:(e.get("date",""),e.get("last_seen","")),reverse=True)
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump({"updated":now,"events":events},f,indent=1,ensure_ascii=False)
    with open(QUEUE,"w",encoding="utf-8") as f:
        json.dump(queue,f,indent=1,ensure_ascii=False)
    remaining=sum(not x.get("processed") for x in queue)
    print("Batches processed:",batch_count,"sources processed:",processed_count,
          "events saved:",len(events),"queue remaining:",remaining)

def main():
    if RUN_MODE=="collect":
        save_queue(gather())
        save_status()
    elif RUN_MODE=="process":
        process_queue()
    else:
        raise SystemExit(f"Unknown RUN_MODE: {RUN_MODE}")

if __name__=="__main__": main()
