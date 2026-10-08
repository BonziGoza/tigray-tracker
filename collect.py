"""Tigray OSINT collector with language-aware translation, event extraction, and deterministic evidence grading."""
import os, json, re, datetime as dt, hashlib, time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser, requests
import trafilatura

OUT="data/events.json"; QUEUE="data/source_queue.json"; STATUS="data/status.json"; TODAY=dt.date.today().isoformat()
KEEP_DAYS=45; QUEUE_DAYS=2; MAX_ITEMS=100; PROCESS_MAX_ITEMS=180; PROCESS_BATCH_SIZE=30
MODEL=os.environ.get("MODEL","gemini-2.5-flash-lite")
ARTICLE_TIMEOUT=15
ARTICLE_MAX_CHARS=12000
ARTICLE_FETCH_WORKERS=6
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

def gather():
    items = gather_news()
    print("items gathered:", len(items), "news:", len(items))
    return items[:MAX_ITEMS]

PROMPT="""You are structuring OSINT reports about Tigray and northern Ethiopia.
Today is {today}. Analyze the actual source content supplied for each NEW source item, not merely its RSS metadata.
For NEWS sources, ARTICLE_TEXT is the primary evidence. The feed title is also source wording. Treat RSS_SUMMARY only as discovery metadata and NEVER use it by itself to establish a location, event detail, date, or claim when ARTICLE_TEXT is unavailable. If ARTICLE_TEXT is unavailable, be conservative.
For SOCIAL sources, use the supplied post text/title as the source content.
First detect the language of the source content. Only when the source text is Amharic (አማርኛ) or Tigrinya (ትግርኛ), translate it to neutral English for analysis. Do NOT translate English text. Preserve the original wording for every translated item and do not silently alter names, places, numbers, dates, or claims. If language detection is uncertain, do not translate; mark language as unknown. Then extract distinct real-world EVENTS from the numbered NEW source items.
Merge reports that clearly describe the same event. If a new report clearly describes an existing event below, reuse that existing event's key.
Do not invent facts. Ignore only clearly irrelevant content.
Do not silently drop a relevant news or social report: if it describes a real development, make or attach it to an event. Political, diplomatic, humanitarian, security, and control developments are still events even when they are not combat.
A social-media post is a report/claim, not proof. Preserve attribution. Do not treat reposts or repeated wording as independent evidence.
Every relevant source item should appear in at least one event's items array. If an item is truly irrelevant, put its index in ignored_items with a brief reason.
Return only the requested JSON. Each event must contain:
key, place, region, date, kind, summary, attribution, items, translations, evidence.
The evidence object must contain source_assessments (one object per source index in the event), specificity ("high", "medium", or "low"), and contradicted (boolean).
Each source assessment must contain source_index, source_role, named_sources, anonymous_sources, direct_observation, official_sources, documentary_evidence, visual_evidence, attributed_claim, source_is_party, and contested.
source_role must be one of direct_report, reported_sourcing, official_statement, party_claim, secondary_report, social_claim, or other.
Count named_sources only when the article/post identifies the person, organization, institution, or document providing information. Count anonymous_sources separately. official_sources means government, military, diplomatic, humanitarian, or party officials quoted or directly cited. direct_observation means the reporting organization says its reporter/correspondent directly witnessed or gathered the information. documentary_evidence means the source relies on a named document, record, imagery, data, court filing, etc. visual_evidence means the source presents or explicitly describes photographs/video as evidence of the reported event. attributed_claim means the central claim is explicitly attributed rather than presented as independently established fact. source_is_party means the claim originates from a party to the conflict. contested means the source itself reports a meaningful denial or dispute.
Do not assume a source is independent merely because it is a different publication.
kind must be control_change, strike, clash, diplomatic, humanitarian, claim, or other.
attribution must be party or independent.
Use only these exact map places: {places}
Regional areas allowed: Northern Tigray, Western Tigray, Eastern Tigray, Southern Tigray, Central Tigray, Northwestern Tigray, Northeastern Tigray.
STRICT LOCATION RULES: A specific place may be assigned ONLY when that exact place is explicitly named in the source title or ARTICLE_TEXT/post text. Do NOT infer a city/town from the outlet, URL slug, RSS query, nearby geography, or general knowledge. If the source explicitly states "Northern Tigray" or another allowed regional area, set region to that exact region and leave place empty. Never convert a regional statement into a city. If no recognized place or region is explicitly stated in the source content, leave both place and region empty. Never infer a town/city from a region or from the general topic. If the source explicitly says "Northern Tigray" or another regional area, set region to that region and leave place empty. If no geographic area is stated, leave both place and region empty. Do not use "unknown", "unconfirmed", "unclear", or similar text as a location.
Use the source publication date if the event date is not explicit. Only assign a place or region when supported by the source.
Summaries must be concise, neutral English and attribute disputed claims such as "TPLF says...". Never leave Amharic or Tigrinya script in the event summary when a translation is available. For translations, include one object per translated source in translations with source_index, language ("am" or "ti"), original_text, and english_translation. For English sources, do not include a translation object.
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
        f"RSS_SUMMARY={x.get('summary','')} | published={x['published']} | url={x['url']}\\n"
        f"ARTICLE_TEXT_AVAILABLE={x.get('article_text_available',False)}\\n"
        f"ARTICLE_TEXT={x.get('article_text','')}"
        for i,x in enumerate(items))
    schema={"type":"ARRAY","items":{"type":"OBJECT","properties":{
        "key":{"type":"STRING"},"place":{"type":"STRING"},"region":{"type":"STRING"},"date":{"type":"STRING"},
        "kind":{"type":"STRING"},"summary":{"type":"STRING"},"attribution":{"type":"STRING"},
        "items":{"type":"ARRAY","items":{"type":"INTEGER"}},
        "ignored_items":{"type":"ARRAY","items":{"type":"INTEGER"}},
        "translations":{"type":"ARRAY","items":{"type":"OBJECT","properties":{
            "source_index":{"type":"INTEGER"},"language":{"type":"STRING"},"original_text":{"type":"STRING"},"english_translation":{"type":"STRING"}},
            "required":["source_index","language","original_text","english_translation"]}}},
        "evidence":{"type":"OBJECT","properties":{
            "source_assessments":{"type":"ARRAY","items":{"type":"OBJECT","properties":{
                "source_index":{"type":"INTEGER"},"source_role":{"type":"STRING"},
                "named_sources":{"type":"INTEGER"},"anonymous_sources":{"type":"INTEGER"},
                "direct_observation":{"type":"BOOLEAN"},"official_sources":{"type":"INTEGER"},
                "documentary_evidence":{"type":"BOOLEAN"},"visual_evidence":{"type":"BOOLEAN"},
                "attributed_claim":{"type":"BOOLEAN"},"source_is_party":{"type":"BOOLEAN"},
                "contested":{"type":"BOOLEAN"}},
                "required":["source_index","source_role","named_sources","anonymous_sources","direct_observation","official_sources","documentary_evidence","visual_evidence","attributed_claim","source_is_party","contested"]}},
            "specificity":{"type":"STRING"},"contradicted":{"type":"BOOLEAN"}},
            "required":["source_assessments","specificity","contradicted"]},
        "required":["key","place","region","date","kind","summary","attribution","items","ignored_items","translations","evidence"]}}
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


def fetch_article_text(item):
    """Fetch and extract a news article body for analysis only; never persist the body."""
    if item.get("source_type") != "news":
        return ""
    url=str(item.get("url","") or "").strip()
    if not url.startswith(("http://","https://")):
        return ""
    try:
        r=requests.get(url,headers={
            "User-Agent":"Mozilla/5.0 (compatible; TigrayTracker/1.0; +https://bonzigoza.github.io/tigray-tracker/)",
            "Accept":"text/html,application/xhtml+xml"
        },timeout=ARTICLE_TIMEOUT,allow_redirects=True)
        r.raise_for_status()
        content_type=(r.headers.get("content-type") or "").lower()
        if "html" not in content_type and "text/" not in content_type:
            return ""
        raw=r.content[:5_000_000]
        text=trafilatura.extract(
            raw,url=r.url,include_comments=False,include_tables=False,
            favor_precision=True,output_format="txt"
        ) or ""
        text=re.sub(r"\s+"," ",text).strip()
        return text[:ARTICLE_MAX_CHARS]
    except Exception as ex:
        print("article fetch failed:",url[:120],type(ex).__name__)
        return ""

def enrich_news_items(items):
    """Add transient article_text to news items before Gemini analysis."""
    targets=[(i,x) for i,x in enumerate(items) if x.get("source_type")=="news"]
    if not targets:
        return items
    results={}
    with ThreadPoolExecutor(max_workers=ARTICLE_FETCH_WORKERS) as pool:
        futures={pool.submit(fetch_article_text,x):i for i,x in targets}
        for future in as_completed(futures):
            i=futures[future]
            try:
                results[i]=future.result() or ""
            except Exception:
                results[i]=""
    enriched=[]
    extracted=0
    for i,item in enumerate(items):
        x=dict(item)
        if x.get("source_type")=="news":
            x["article_text"]=results.get(i,"")
            x["article_text_available"]=bool(x["article_text"])
            if x["article_text"]:
                extracted+=1
        enriched.append(x)
    print("article bodies extracted:",extracted,"/",len(targets))
    return enriched

def contains_ethio_script(text):
    return bool(re.search(r"[\u1200-\u137F]", str(text or "")))

def translate_non_english_items(items):
    """Translate Amharic/Tigrinya source items to neutral English when Gemini is available."""
    if not API_KEY: return {}
    targets=[(i,x) for i,x in enumerate(items) if (
        contains_ethio_script(x.get("title","")) or
        contains_ethio_script(x.get("summary","")) or
        contains_ethio_script(x.get("article_text",""))
    )]
    if not targets: return {}
    listing="\n".join(
        f'{i}. TITLE: {x["title"]} | RSS_SUMMARY: {x.get("summary","")} | '
        f'ARTICLE_TEXT: {x.get("article_text","")[:8000]}'
        for i,x in targets)
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


SOURCE_PROFILES = [
    ("reuters", "A", 45, "Reuters"),
    ("associated press", "A", 44, "Associated Press"),
    ("ap news", "A", 44, "AP News"),
    ("apnews", "A", 44, "AP News"),
    ("afp", "A", 42, "AFP"),
    ("bbc", "A", 40, "BBC"),
    ("cnn", "A", 38, "CNN"),
    ("al jazeera", "A", 37, "Al Jazeera"),
    ("france 24", "A", 36, "France 24"),
    ("dw", "A", 36, "DW"),
    ("new york times", "A", 35, "The New York Times"),
    ("the guardian", "A", 34, "The Guardian"),
    ("africanews", "B", 31, "Africanews"),
    ("addis standard", "B", 30, "Addis Standard"),
    ("allafrica", "B", 29, "AllAfrica"),
    ("semafor", "B", 29, "Semafor"),
    ("al-monitor", "B", 29, "Al-Monitor"),
    ("foreign policy", "B", 29, "Foreign Policy"),
    ("voa", "B", 29, "VOA"),
    ("borkena", "B", 27, "Borkena"),
    ("fana", "B", 26, "Fana"),
    ("tigrai television", "B", 26, "Tigrai Television"),
    ("tikvah", "B", 25, "TIKVAH"),
    ("tikvahethiopia", "B", 25, "TIKVAH Ethiopia"),
    ("axumawian", "C", 22, "Axumawian"),
]

def source_profile(source):
    if source.get("source_type") == "social":
        return {"tier":"D","base":12,"label":source.get("platform","Social")}
    outlet=(source.get("outlet") or "").lower().strip()
    for needle,tier,base,label in sorted(SOURCE_PROFILES,key=lambda x:len(x[0]),reverse=True):
        if needle in outlet:
            return {"tier":tier,"base":base,"label":label}
    return {"tier":"C","base":18,"label":source.get("outlet") or "Unknown source"}

def source_quality(source):
    return source_profile(source)["base"]

def independent_sources(sources):
    seen_fingerprints=set()
    out=[]
    for source in sources:
        fp=source.get("repost_of_fingerprint") or source.get("fingerprint")
        if fp and fp in seen_fingerprints:
            continue
        if fp:
            seen_fingerprints.add(fp)
        out.append(source)
    return out

def _source_assessment(source):
    e=source.get("evidence") or {}
    return {
        "named":max(0,min(5,int(e.get("named_sources",0) or 0))),
        "anonymous":max(0,min(5,int(e.get("anonymous_sources",0) or 0))),
        "direct":bool(e.get("direct_observation",False)),
        "official":max(0,min(3,int(e.get("official_sources",0) or 0))),
        "documentary":bool(e.get("documentary_evidence",False)),
        "visual":bool(e.get("visual_evidence",False)),
        "attributed":bool(e.get("attributed_claim",False)),
        "party":bool(e.get("source_is_party",False)),
        "contested":bool(e.get("contested",False)),
    }

def reporting_quality(source):
    e=_source_assessment(source)
    score=min(10,e["named"]*3+(1 if e["named"]>=2 else 0))
    score+=min(4,e["official"]*2)
    if e["direct"]: score+=5
    if e["documentary"]: score+=4
    if e["visual"]: score+=2
    score=max(0,score-min(4,e["anonymous"]))
    return min(25,score)

def corroboration_score(sources):
    src=independent_sources(sources)
    news=[s for s in src if s.get("source_type")=="news"]
    social=[s for s in src if s.get("source_type")=="social"]
    profiles=[source_profile(s) for s in news]
    a=sum(p["tier"]=="A" for p in profiles)
    b=sum(p["tier"]=="B" for p in profiles)
    c=sum(p["tier"]=="C" for p in profiles)
    score=0
    if a>=2: score+=10
    if a>=3: score+=6
    if a>=4: score+=3
    if b>=2: score+=7
    if b>=3: score+=4
    if c>=2: score+=4
    if news and social: score+=min(3,len(social))
    elif len(social)>=2: score+=min(2,len(social)-1)
    return min(25,score)

def evidence_score(sources,attribution="independent",event_evidence=None):
    src=independent_sources(sources)
    if not src:
        return 10
    best=max(src,key=source_quality)
    publisher=source_quality(best)
    reporting=max((reporting_quality(s) for s in src),default=0)
    corroboration=corroboration_score(src)
    context=0
    ee=event_evidence or {}
    specificity=str(ee.get("specificity","")).lower()
    if specificity=="high": context+=4
    elif specificity=="medium": context+=2
    if any((s.get("evidence") or {}).get("direct_observation") for s in src):
        context+=1
    score=publisher+reporting+corroboration+min(5,context)
    party_sources=sum(_source_assessment(s)["party"] for s in src)
    attributed_claims=sum(_source_assessment(s)["attributed"] for s in src)
    contested=bool(ee.get("contradicted",False)) or any(_source_assessment(s)["contested"] for s in src)
    if attribution=="party": score-=8
    if party_sources and party_sources==len(src): score-=7
    if attributed_claims and not corroboration: score-=4
    if contested: score-=10
    if not any(s.get("source_type")=="news" for s in src): score=min(score,39)
    if len(src)==1 and source_profile(best)["tier"]=="A": score=min(score,78)
    elif len(src)==1 and source_profile(best)["tier"]=="B": score=min(score,64)
    return max(5,min(98,int(round(score))))

def grade(sources,attribution="independent",event_evidence=None):
    src=independent_sources(sources)
    news=[s for s in src if s.get("source_type")=="news"]
    a=[s for s in news if source_profile(s)["tier"]=="A"]
    b=[s for s in news if source_profile(s)["tier"]=="B"]
    score=evidence_score(src,attribution,event_evidence)
    if score>=90 and (len(a)>=2 or (len(a)>=1 and len(b)>=2)):
        return "CONFIRMED"
    if score>=75 and (len(a)>=2 or len(news)>=3):
        return "STRONGLY CORROBORATED"
    if score>=60 and (len(a)>=2 or len(b)>=2 or len(news)>=2):
        return "CORROBORATED"
    if news:
        return "REPORTED"
    if len(src)>=2:
        return "DEVELOPING"
    return "CLAIM"

def confidence(sources,attribution="independent",event_evidence=None):
    return evidence_score(sources,attribution,event_evidence)

def evidence_explanation(sources,event_evidence=None):
    src=independent_sources(sources)
    if not src:
        return "No source evidence available."
    profiles=[source_profile(s) for s in src]
    best=max(profiles,key=lambda p:p["base"])
    labels=[]
    for p in profiles:
        if p["label"] not in labels:
            labels.append(p["label"])
    a=sum(p["tier"]=="A" for p in profiles)
    b=sum(p["tier"]=="B" for p in profiles)
    c=sum(p["tier"]=="C" for p in profiles)
    social=sum(s.get("source_type")=="social" for s in src)
    parts=[f"Best source: {best['label']} ({best['tier']}-tier)."]
    parts.append(f"{len(src)} independent source record{'s' if len(src)!=1 else ''}; {a} A-tier, {b} B-tier, {c} C-tier, {social} social.")
    rq=max((reporting_quality(s) for s in src),default=0)
    if rq>=18: parts.append("Strong source-level reporting/sourcing.")
    elif rq>=10: parts.append("Moderate source-level reporting/sourcing.")
    else: parts.append("Limited source-level sourcing.")
    if event_evidence and event_evidence.get("contradicted"):
        parts.append("Material contradiction detected.")
    elif event_evidence and any((s.get("evidence") or {}).get("contested") for s in src):
        parts.append("A meaningful dispute/denial is reported.")
    return " ".join(parts)

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
    assessments={}
    raw_evidence=n.get("evidence") or {}
    if isinstance(raw_evidence,dict):
        for a in raw_evidence.get("source_assessments",[]):
            if isinstance(a,dict) and isinstance(a.get("source_index"),int):
                assessments[a["source_index"]]=a
    for i in n.get("items",[]):
        if isinstance(i,int) and 0<=i<len(items):
            s=items[i]
            record={"outlet":s["outlet"],"url":s["url"],"title":s.get("original_title",s["title"]),
                "source_type":s["source_type"],"platform":s["platform"],"author":s.get("author",""),
                "published":s.get("published",""),"fingerprint":s.get("fingerprint",""),
                "repost_of_fingerprint":s.get("repost_of_fingerprint","")}
            if i in assessments:
                record["evidence"]=assessments[i]
            if s["url"] not in have:
                ev["sources"].append(record); have.add(s["url"])
            elif i in assessments:
                for existing_source in ev["sources"]:
                    if existing_source.get("url")==s["url"]:
                        existing_source["evidence"]=assessments[i]
                        break
    if contains_ethio_script(ev.get("summary","")):
        translated_for_event=[x.get("english_translation") for x in ev.get("translations",[]) if x.get("english_translation")]
        if translated_for_event:
            ev["summary"]=translated_for_event[0][:500]
    event_evidence=raw_evidence if isinstance(raw_evidence,dict) else {}
    ev["evidence"]=event_evidence
    ev["grade"]=grade(ev["sources"],ev.get("attribution","independent"),event_evidence)
    ev["confidence"]=confidence(ev["sources"],ev.get("attribution","independent"),event_evidence)
    ev["source_count"]=len(independent_sources(ev["sources"]))
    ev["social_source_count"]=sum(s.get("source_type")=="social" for s in ev["sources"])
    ev["news_source_count"]=sum(s.get("source_type")=="news" for s in ev["sources"])
    profiles=[source_profile(s) for s in independent_sources(ev["sources"])]
    best_profile=max(profiles,key=lambda p:p["base"]) if profiles else {"tier":"D","label":"None","base":0}
    ev["source_tier"]=best_profile["tier"]
    ev["best_source"]=best_profile["label"]
    ev["independent_source_count"]=len(independent_sources(ev["sources"]))
    ev["high_quality_source_count"]=sum(p["tier"]=="A" for p in profiles)
    ev["evidence_explanation"]=evidence_explanation(ev["sources"],event_evidence)
    db[key]=ev

def rescore_event(ev):
    """Recalculate score/grade for stored events after scoring-model changes."""
    if not isinstance(ev,dict) or ev.get("manual"):
        return ev
    sources=ev.get("sources") or []
    event_evidence=ev.get("evidence") if isinstance(ev.get("evidence"),dict) else {}
    ev["grade"]=grade(sources,ev.get("attribution","independent"),event_evidence)
    ev["confidence"]=confidence(sources,ev.get("attribution","independent"),event_evidence)
    profiles=[source_profile(s) for s in independent_sources(sources)]
    best=max(profiles,key=lambda p:p["base"]) if profiles else {"tier":"D","label":"None","base":0}
    ev["source_tier"]=best["tier"]
    ev["best_source"]=best["label"]
    ev["source_count"]=len(independent_sources(sources))
    ev["independent_source_count"]=len(independent_sources(sources))
    ev["high_quality_source_count"]=sum(p["tier"]=="A" for p in profiles)
    ev["evidence_explanation"]=evidence_explanation(sources,event_evidence)
    return ev

def deterministic_fallback(items):
    """Conservative fallback that groups obvious duplicates and keeps every source."""
    groups=[]
    for i,item in enumerate(items):
        # Fallback location extraction must never use an RSS summary for news.
        # For news, use only the article title/body; for social, use the post text.
        if item.get("source_type")=="news":
            text=(item.get("title","")+" "+item.get("article_text","")).strip()
        else:
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
    # Social sources are disabled; keep only the news queue while preserving processed news.
    queue=[x for x in load_json(QUEUE, []) if x.get("source_type")=="news"]
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
    queue=[x for x in load_json(QUEUE, []) if x.get("source_type")=="news"]
    pending_all=sorted((x for x in queue if not x.get("processed")), key=published_sort_key, reverse=True)

    # Rescore stored events on every processing run so scoring-model changes
    # take effect even when there are no new source items.
    data=load_json(OUT, {"events":[]})
    db={e["key"]:e for e in data.get("events",[]) if e.get("key")}
    # Social/Telegram sources are intentionally disabled for now. Remove them from stored events.
    for key,ev in list(db.items()):
        ev["sources"]=[x for x in ev.get("sources",[]) if x.get("source_type")=="news"]
        if not ev["sources"]:
            db.pop(key, None)
            continue
        ev["social_source_count"]=0
    for key,ev in list(db.items()):
        db[key]=rescore_event(ev)

    if not pending_all:
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        events=sorted(db.values(),key=lambda e:(e.get("date",""),e.get("last_seen","")),reverse=True)
        with open(OUT,"w",encoding="utf-8") as f:
            json.dump({"updated":now,"events":events},f,indent=1,ensure_ascii=False)
        print("No new source items; stored events rescored:",len(events))
        return

    # Work in bounded batches so a large Telegram burst cannot crowd out news,
    # and so one model response cannot accidentally merge unrelated stories.
    pending_all=pending_all[:PROCESS_MAX_ITEMS]
    processed_count=0
    batch_count=0

    for offset in range(0,len(pending_all),PROCESS_BATCH_SIZE):
        batch=pending_all[offset:offset+PROCESS_BATCH_SIZE]
        if not batch: continue
        batch_count+=1

        # Fetch actual article bodies transiently. They are passed to Gemini
        # but never written to source_queue.json or events.json.
        batch=enrich_news_items(batch)

        # Translate first so Gemini sees English text for Amharic/Tigrinya social
        # sources while we still preserve the original source text.
        translations=translate_non_english_items(batch)
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
