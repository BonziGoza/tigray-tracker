"""Experimental, transparent, non-operational regional conflict outlook."""
import json, math, os, re, datetime as dt
from collections import defaultdict
EVENTS="data/events.json"; OUT="data/forecasts.json"; HISTORY="data/forecast_history.json"
LOOKBACK_DAYS=21; HORIZON_DAYS=7; HALF_LIFE_DAYS=4.0
# Geographic aggregation only; does not change an event's extracted location.
PLACE_REGION={
"Mekelle":"Central Tigray","Mekele":"Central Tigray","Agula":"Central Tigray",
"Wukro":"Eastern Tigray","Adigrat":"Eastern Tigray","Zalambessa":"Eastern Tigray","Idaga Hamus":"Eastern Tigray",
"Adwa":"Central Tigray","Axum":"Central Tigray","Shire":"Northwestern Tigray","Humera":"Western Tigray",
"Alamata":"Southern Tigray","Hagere Selam":"Southeastern Tigray","Tslimoy":"Northwestern Tigray",
"Abiy Addi":"Central Tigray","Kobo":"Amhara","Woldia":"Amhara","Dessie":"Amhara","Lalibela":"Amhara",
"Sekota":"Amhara","Bahir Dar":"Amhara","Gondar":"Amhara","Semera":"Afar","Abala":"Afar",
"Erebti":"Afar","Megale":"Afar","Asmara":"Eritrea","Addis Ababa":"Addis Ababa"}
KIND={"clash":1.0,"strike":1.0,"control_change":0.9,"humanitarian":0.7,"diplomatic":0.55,"claim":0.35,"other":0.4}
GRADE={"CONFIRMED":1.0,"STRONGLY CORROBORATED":0.9,"CORROBORATED":0.78,"REPORTED":0.62,"DEVELOPING":0.48,"CLAIM":0.25}
def date_of(v):
    try:return dt.date.fromisoformat(str(v)[:10])
    except Exception:return None
def quality(e):
    ss=e.get("sources") or []
    if not ss:return 0.35
    vals=[]
    for s in ss:
        try: vals.append(max(.1,min(1,float(s.get("credibility_score",42))/100)))
        except Exception: vals.append({"STRONG":1,"MODERATE":.72,"LIMITED":.42}.get(s.get("credibility_label"),.42))
    vals.sort(reverse=True)
    return min(1,vals[0]+sum(x*.12 for x in vals[1:3]))
def weight(e,today):
    d=date_of(e.get("date")) or date_of(e.get("last_seen"))
    if not d or (today-d).days < -1 or (today-d).days > LOOKBACK_DAYS:return 0
    age=max(0,(today-d).days); decay=math.pow(.5,age/HALF_LIFE_DAYS)
    conf=max(.15,min(1,float(e.get("confidence",35))/100))
    return decay*KIND.get(e.get("kind","other"),.4)*(.35+.35*GRADE.get(e.get("grade","REPORTED"),.55)+.30*quality(e))*(.55+.45*conf)
def region_for(e):
    return (e.get("region") or "").strip() or PLACE_REGION.get((e.get("place") or "").strip())
def event_text(e):
    text=str(e.get("summary") or "").lower()
    text=re.sub(r"\s[-|–—]\s[^-|–—]{1,45}$","",text)
    return set(re.findall(r"[a-z0-9]{3,}",text))
def deduplicate(rows):
    """Collapse near-identical event records before regional scoring."""
    kept=[]; duplicate_count=0; tokens=[]
    for e,w in sorted(rows,key=lambda pair:pair[1],reverse=True):
        words=event_text(e); d=date_of(e.get("date")) or date_of(e.get("last_seen"))
        region=region_for(e) or (e.get("place") or "").strip() or "unlocated"
        duplicate=False
        for prior,prior_w,prior_words,prior_date,prior_region in tokens:
            if region!=prior_region or e.get("kind","other")!=prior.get("kind","other") or not words or not prior_words:
                continue
            if d and prior_date and abs((d-prior_date).days)>2: continue
            overlap=len(words & prior_words)/max(1,len(words | prior_words))
            if overlap>=0.80:
                duplicate=True; break
        if duplicate:
            duplicate_count+=1
        else:
            kept.append((e,w));tokens.append((e,w,words,d,region))
    return kept,duplicate_count
def main():
    today=dt.datetime.now(dt.timezone.utc).date()
    with open(EVENTS,encoding="utf-8") as f: db=json.load(f)
    recent=[(e,weight(e,today)) for e in db.get("events",[])]
    recent=[(e,w) for e,w in recent if w>0]
    recent,duplicate_records_ignored=deduplicate(recent)
    grouped=defaultdict(list)
    for e,w in recent:
        r=region_for(e)
        if r:grouped[r].append((e,w))
    regions=[]
    for r,rows in grouped.items():
        total=sum(w for _,w in rows)
        hard=sum(w for e,w in rows if e.get("kind") in ("clash","strike","control_change"))
        control=sum(w for e,w in rows if e.get("kind")=="control_change")
        early=sum(w*{"CONFIRMED":.15,"STRONGLY CORROBORATED":.25,"CORROBORATED":.35,"REPORTED":.55,"DEVELOPING":.8,"CLAIM":.95}.get(e.get("grade","REPORTED"),.6) for e,w in rows)/max(sum(w for _,w in rows),.01)
        idx=round(100*(1-math.exp(-.42*(hard+.35*total))))
        level="ELEVATED" if idx>=65 else "GUARDED" if idx>=38 else "WATCH"
        examples=[]; seen=set()
        for e,_ in sorted(rows,key=lambda z:z[1],reverse=True):
            title=(e.get("summary") or e.get("place") or e.get("region") or "Reported development")[:180]
            if title in seen:continue
            seen.add(title)
            examples.append({"date":e.get("date",""),"title":title,"grade":e.get("grade","REPORTED"),
                "sources":[{"outlet":s.get("outlet","Source"),"url":s.get("url","")} for s in (e.get("sources") or [])[:2] if s.get("url")]})
            if len(examples)>=3:break
        regions.append({"region":r,"risk_index":idx,"level":level,"uncertainty":round(100*min(.95,early)),
            "event_count":len(rows),"weighted_signal":round(total,2),"control_change_signal":round(control,2),
            "explanation":f"{len(rows)} recent event records weighted by recency, event type, existing evidence grade, and article credibility. {sum(1 for e,_ in rows if e.get('grade') in ('CLAIM','DEVELOPING','REPORTED'))} records are claim/developing-grade; source uncertainty is material.",
            "examples":examples})
    regions.sort(key=lambda r:(r["risk_index"],r["weighted_signal"]),reverse=True)
    total=sum(w for _,w in recent)
    hard=sum(w for e,w in recent if e.get("kind") in ("clash","strike","control_change"))
    cross=sum(w for e,w in recent if any(k in (str(e.get("summary",""))+" "+str(e.get("region",""))+" "+str(e.get("place",""))).lower() for k in ("eritrea","eritrean","border","zelambessa","adigrat")))
    diplomacy=sum(w for e,w in recent if e.get("kind")=="diplomatic")
    control=sum(w for e,w in recent if e.get("kind")=="control_change")
    early=sum(w*{"CONFIRMED":.15,"STRONGLY CORROBORATED":.25,"CORROBORATED":.35,"REPORTED":.55,"DEVELOPING":.8,"CLAIM":.95}.get(e.get("grade","REPORTED"),.6) for e,w in recent)/max(total,.01)
    # Relative scenario weights are transparent heuristics, not calibrated probabilities.
    raw=[
      ("Continued localized conflict and shifting control",1+1.7*hard+.6*control,"Recent clash, strike, and control-change reporting supports continued instability as a plausible scenario; this does not predict a specific operation or outcome."),
      ("Wider cross-border escalation",.8+1.6*cross+.8*diplomacy,"Cross-border and diplomatic signals appear in recent reporting. Claims can be disputed and do not establish intent."),
      ("Relative stabilization or a temporary pause",1.1+.8*max(0,4-hard)+.25*diplomacy,"A pause remains plausible, but recent reports alone cannot establish a durable ceasefire or political settlement.")]
    vals=[math.sqrt(max(.1,x[1])) for x in raw]; denom=sum(vals); scenarios=[]
    for (name,_,why),v in zip(raw,vals):scenarios.append({"name":name,"weight":round(100*v/denom),"rationale":why})
    scenarios[-1]["weight"]+=100-sum(x["weight"] for x in scenarios)
    payload={"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"horizon_days":HORIZON_DAYS,"lookback_days":LOOKBACK_DAYS,
      "method":"experimental_heuristic_v1","status":"EXPERIMENTAL — NOT CALIBRATED",
      "disclaimer":"Relative scenario weights and regional indicators, not validated probabilities, predictions of specific territorial outcomes, or operational intelligence. Coverage gaps, censorship, access restrictions, duplicated reports, and disputed claims can distort the signal. No event is inferred from an absent report.",
      "summary":{"recent_event_records":len(recent),"regions_with_located_evidence":len(regions),"control_change_records":sum(1 for e,_ in recent if e.get("kind")=="control_change"),
        "contested_or_early_records":sum(1 for e,_ in recent if e.get("grade") in ("CLAIM","DEVELOPING")),"reported_records":sum(1 for e,_ in recent if e.get("grade")=="REPORTED"),"duplicate_records_ignored":duplicate_records_ignored,"overall_evidence_uncertainty":round(100*min(1,early))},
      "scenarios":scenarios,"regions":regions}
    os.makedirs("data",exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f:json.dump(payload,f,ensure_ascii=False,indent=2)
    history=[]
    if os.path.exists(HISTORY):
      try:
        with open(HISTORY,encoding="utf-8") as f:history=json.load(f)
      except Exception:history=[]
    snap={"date":today.isoformat(),"generated_at":payload["generated_at"],"horizon_days":HORIZON_DAYS,"scenarios":scenarios,
      "regions":[{"region":r["region"],"risk_index":r["risk_index"],"level":r["level"]} for r in regions]}
    if not history or history[-1].get("date")!=today.isoformat():history.append(snap)
    else:history[-1]=snap
    history=history[-120:]
    with open(HISTORY,"w",encoding="utf-8") as f:json.dump(history,f,ensure_ascii=False,indent=2)
    print(f"Wrote forecast for {len(regions)} regions; {len(scenarios)} scenarios; {len(history)} daily snapshots")
if __name__=="__main__":main()
