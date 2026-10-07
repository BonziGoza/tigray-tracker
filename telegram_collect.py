"""Collect recent public Telegram channel posts into the shared OSINT source queue."""
import os, json, re, datetime as dt, hashlib
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

QUEUE="data/source_queue.json"
CHANNELS=[
    "Tigrai_Ttv",
    "axumawianmedia",
    "tigrignafana",
    "tikvahethiopiA",
    "tikvahethiopiatigrigna",
    "ASCENTIG",
]
KEYWORDS=["tigray","tigrinya","tigrigna","mekelle","mekele","tplf","eritrea","afar","amhara","fano","abiy","ethiopia"]
LOOKBACK_HOURS=48
MAX_PER_CHANNEL=25
MAX_NEW_ITEMS=80

def normalize(text):
    text=re.sub(r"\\s+"," ",text or "").strip().lower()
    return re.sub(r"[^\\w\\u00c0-\\u024f\\u0370-\\u052f\\u1200-\\u137f ]","",text)

def fingerprint(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:20]

def load_queue():
    if not os.path.exists(QUEUE):
        return []
    try:
        with open(QUEUE,encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def main():
    api_id=os.environ.get("TELEGRAM_API_ID","")
    api_hash=os.environ.get("TELEGRAM_API_HASH","")
    session=os.environ.get("TELEGRAM_SESSION","")
    if not (api_id and api_hash and session):
        raise SystemExit("Telegram credentials/session are not configured.")

    queue=load_queue()
    existing_urls={x.get("url") for x in queue}
    existing_fps={x.get("fingerprint") for x in queue if x.get("fingerprint")}
    cutoff=dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=LOOKBACK_HOURS)
    new_items=[]

    with TelegramClient(
        StringSession(session), int(api_id), api_hash,
        device_model="Tigray Tracker", system_version="GitHub Actions", app_version="1.0"
    ) as client:
        me=client.get_me()
        print("Telegram authorized as:", getattr(me,"username",None) or "user")
        for username in CHANNELS:
            count=0
            try:
                for msg in client.iter_messages(username, limit=MAX_PER_CHANNEL):
                    if not msg or not msg.date or msg.date < cutoff:
                        continue
                    text=msg.message or ""
                    if not text.strip():
                        continue
                    low=text.lower()
                    if not any(k in low for k in KEYWORDS):
                        continue

                    url=f"https://t.me/{username}/{msg.id}"
                    if url in existing_urls:
                        continue

                    fp=fingerprint(text)
                    item={
                        "title":text.strip().splitlines()[0][:300],
                        "outlet":username,
                        "url":url,
                        "summary":text.strip()[:600],
                        "source_type":"social",
                        "platform":"telegram",
                        "author":username,
                        "published":msg.date.astimezone(dt.timezone.utc).isoformat(),
                        "fingerprint":fp,
                    }
                    if fp in existing_fps:
                        item["repost_of_fingerprint"]=fp
                    else:
                        existing_fps.add(fp)

                    queue.append(item)
                    new_items.append(item)
                    existing_urls.add(url)
                    count+=1
                print(username, "new:", count)
            except Exception as ex:
                print("Telegram channel failed:", username, ex)

    queue=queue[-500:]
    with open(QUEUE,"w",encoding="utf-8") as f:
        json.dump(queue,f,indent=1,ensure_ascii=False)
    print("Telegram new items:",len(new_items))

if __name__=="__main__":
    main()
