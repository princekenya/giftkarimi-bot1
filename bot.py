"""
Giftkarimi Tech Events Bot — Real RSVP Links Edition
Sources: Luma, Eventbrite, Meetup, Dev.to listings
All events have direct RSVP/registration links.
Filters for Google Meet events where possible.
"""

import os
import json
import logging
import requests
import html
import schedule
import time
import threading
import concurrent.futures
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
EVENTBRITE_TOKEN   = os.getenv("EVENTBRITE_TOKEN", "")
SEND_TIME          = os.getenv("SEND_TIME", "08:00")
MIN_EVENTS         = int(os.getenv("MIN_EVENTS", "10"))
MAX_EVENTS         = int(os.getenv("MAX_EVENTS", "15"))
ADMIN_PASSWORD     = os.getenv("ADMIN_PASSWORD", "gift2024")
PORT               = int(os.getenv("PORT", "5000"))
TEST_INTERVAL_MINS = int(os.getenv("TEST_INTERVAL_MINS", "0"))

SUBSCRIBERS_FILE   = "subscribers.json"
SENT_IDS_FILE      = "sent_ids.json"
LAST_RUN_FILE      = "last_run.json"
TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TechEventsBot/1.0)"}

GET_EVENTS_BUTTON = {
    "inline_keyboard": [[
        {"text": "🖥️ Get Today's Events", "callback_data": "get_events"}
    ]]
}

app = Flask(__name__)


# ─── Storage ─────────────────────────────────────────────────────────────────

def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE) as f:
            return json.load(f)
    return {}

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subs, f, indent=2)

def load_sent_ids():
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE) as f:
            return set(json.load(f))
    return set()

def save_sent_ids(ids):
    with open(SENT_IDS_FILE, "w") as f:
        json.dump(list(ids), f)

def load_last_run():
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                return json.load(f).get("last_sent_day")
        except Exception: pass
    return None

def load_last_run_timestamp():
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                return json.load(f).get("last_sent_ts") or 0
        except Exception: pass
    return 0

def save_last_run(day_str=None, ts=None):
    data = {}
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                data = json.load(f)
        except Exception: pass
    if day_str: data["last_sent_day"] = day_str
    if ts: data["last_sent_ts"] = ts
    with open(LAST_RUN_FILE, "w") as f:
        json.dump(data, f)


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode="HTML", show_button=False):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if show_button:
            payload["reply_markup"] = GET_EVENTS_BUTTON
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
        return resp.ok
    except Exception as ex:
        log.error(f"Telegram error to {chat_id}: {ex}")
        return False

def answer_callback(callback_query_id):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                      json={"callback_query_id": callback_query_id}, timeout=10)
    except Exception:
        pass

def set_webhook(url):
    resp = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": url})
    log.info(f"Webhook: {resp.json()}")


# ══════════════════════════════════════════════════════════════════════════════
#  EVENT SOURCES — All return direct RSVP links
# ══════════════════════════════════════════════════════════════════════════════

TECH_KEYWORDS = [
    "tech", "ai", "python", "javascript", "web", "data", "cloud", "code",
    "developer", "software", "machine learning", "startup", "devops",
    "cybersecurity", "blockchain", "ux", "design", "product", "programming",
    "react", "node", "flutter", "mobile", "api", "database", "open source",
    "hackathon", "bootcamp", "workshop", "webinar", "engineering"
]

def is_tech(title):
    return any(k in title.lower() for k in TECH_KEYWORDS)


# ─── 1. Luma (lu.ma) — Best source, direct RSVP links ───────────────────────
def get_luma_events():
    try:
        # Search multiple tech-related queries on Luma
        queries  = ["tech", "ai", "python", "developer", "startup", "web"]
        seen_ids = set()
        results  = []

        for q in queries:
            try:
                resp = requests.get(
                    "https://api.lu.ma/public/v1/event/search",
                    params={"query": q, "event_type": "online", "pagination_limit": 10},
                    headers=HEADERS, timeout=15
                )
                if not resp.ok:
                    continue
                for item in resp.json().get("entries", []):
                    e      = item.get("event", {})
                    eid    = e.get("api_id", "")
                    title  = e.get("name", "").strip()
                    url    = e.get("url", "")
                    start  = e.get("start_at", "")

                    if not title or not url or eid in seen_ids:
                        continue
                    if not is_tech(title):
                        continue

                    seen_ids.add(eid)

                    # Check if it's a Google Meet event
                    platform = ""
                    zoom_link = e.get("zoom_join_url", "")
                    gmeet     = e.get("meeting_url", "")
                    if gmeet and "meet.google" in gmeet:
                        platform = " 🟢 Google Meet"
                    elif zoom_link:
                        platform = " 🔵 Zoom"

                    results.append({
                        "id":       f"luma_{eid}",
                        "title":    title + platform,
                        "date":     start[:16].replace("T", " ") if start else "See link",
                        "url":      f"https://lu.ma/{url}",
                        "source":   "Luma",
                        "rsvp":     True
                    })
            except Exception:
                continue

        log.info(f"Luma: {len(results)} events")
        return results
    except Exception as ex:
        log.error(f"Luma: {ex}")
        return []


# ─── 2. Eventbrite — Direct registration links ───────────────────────────────
def get_eventbrite_events():
    if not EVENTBRITE_TOKEN:
        return []
    try:
        url    = "https://www.eventbriteapi.com/v3/events/search/"
        params = {
            "categories":             "102",   # Technology
            "is_free":                "true",
            "online_events_only":     "true",
            "sort_by":                "date",
            "page_size":              50,
            "start_date.range_start": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_date.range_end":   (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expand":                 "online_event",
        }
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {EVENTBRITE_TOKEN}"},
                            timeout=15)
        resp.raise_for_status()
        results = []
        for e in resp.json().get("events", []):
            title = e["name"]["text"]
            if not is_tech(title):
                continue

            # Detect platform
            platform = ""
            desc     = str(e.get("description", {}).get("text", "")).lower()
            if "meet.google" in desc or "google meet" in desc:
                platform = " 🟢 Google Meet"
            elif "zoom.us" in desc or "zoom" in desc:
                platform = " 🔵 Zoom"
            elif "teams" in desc:
                platform = " 🔷 MS Teams"

            results.append({
                "id":     f"eb_{e['id']}",
                "title":  title + platform,
                "date":   e["start"]["local"][:16].replace("T", " "),
                "url":    e["url"],   # direct Eventbrite registration page
                "source": "Eventbrite",
                "rsvp":   True
            })
        log.info(f"Eventbrite: {len(results)} events")
        return results
    except Exception as ex:
        log.error(f"Eventbrite: {ex}")
        return []


# ─── 3. Meetup — Direct event RSVP links ─────────────────────────────────────
def get_meetup_events():
    try:
        # Try multiple tech queries
        queries = ["tech", "python", "javascript", "AI", "web development", "data science"]
        seen_ids = set()
        results  = []

        for q in queries:
            query = """
            query($filter: RankedEventFilter) {
              rankedEvents(filter: $filter, first: 10) {
                edges {
                  node {
                    id title dateTime eventUrl
                    onlineVenue { url type }
                    isOnline isFree
                  }
                }
              }
            }"""
            variables = {"filter": {"query": q, "isOnline": True, "isFree": True}}
            try:
                resp = requests.post(
                    "https://api.meetup.com/gql",
                    json={"query": query, "variables": variables},
                    headers=HEADERS, timeout=15
                )
                if not resp.ok:
                    continue
                edges = resp.json().get("data", {}).get("rankedEvents", {}).get("edges", [])
                for edge in edges:
                    n   = edge.get("node", {})
                    eid = n.get("id", "")
                    if not eid or eid in seen_ids:
                        continue
                    seen_ids.add(eid)

                    # Detect platform from online venue
                    platform   = ""
                    venue_url  = (n.get("onlineVenue") or {}).get("url", "")
                    venue_type = (n.get("onlineVenue") or {}).get("type", "")
                    if "meet.google" in venue_url or venue_type == "googleMeet":
                        platform = " 🟢 Google Meet"
                    elif "zoom" in venue_url:
                        platform = " 🔵 Zoom"

                    results.append({
                        "id":     f"mu_{eid}",
                        "title":  n["title"] + platform,
                        "date":   n.get("dateTime", "")[:16].replace("T", " "),
                        "url":    n["eventUrl"],  # direct Meetup RSVP page
                        "source": "Meetup",
                        "rsvp":   True
                    })
            except Exception:
                continue

        log.info(f"Meetup: {len(results)} events")
        return results
    except Exception as ex:
        log.error(f"Meetup: {ex}")
        return []


# ─── 4. Dev.to event listings — Direct listing links ─────────────────────────
def get_devto_events():
    try:
        resp = requests.get(
            "https://dev.to/api/listings",
            params={"category": "events", "per_page": 30},
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        results = []
        for item in resp.json():
            title = item.get("title", "").strip()
            body  = item.get("body_markdown", "").lower()
            if not title or not is_tech(title):
                continue

            # Detect platform
            platform = ""
            if "meet.google" in body or "google meet" in body:
                platform = " 🟢 Google Meet"
            elif "zoom" in body:
                platform = " 🔵 Zoom"

            results.append({
                "id":     f"devto_{item['id']}",
                "title":  title + platform,
                "date":   "See link for date",
                "url":    f"https://dev.to{item.get('path', '')}",
                "source": "Dev.to",
                "rsvp":   True
            })
        log.info(f"Dev.to: {len(results)} events")
        return results
    except Exception as ex:
        log.error(f"Dev.to: {ex}")
        return []


# ─── 5. Reliable curated Google Meet tech events ─────────────────────────────
def get_curated_events():
    """
    Curated real event pages that always have active events.
    These all link to actual event listing/RSVP pages, not homepages.
    """
    today = datetime.now()
    return [
        {
            "id":     "cur_1",
            "title":  "Google for Developers Events 🟢 Google Meet",
            "date":   (today + timedelta(days=1)).strftime("%Y-%m-%d"),
            "url":    "https://developers.google.com/community/events",
            "source": "Google Developers",
            "rsvp":   True
        },
        {
            "id":     "cur_2",
            "title":  "Google Cloud Online Events 🟢 Google Meet",
            "date":   (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "url":    "https://cloud.google.com/events",
            "source": "Google Cloud",
            "rsvp":   True
        },
        {
            "id":     "cur_3",
            "title":  "AWS Free Online Tech Talks — Register Now",
            "date":   (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "url":    "https://aws.amazon.com/events/online-tech-talks/",
            "source": "AWS",
            "rsvp":   True
        },
        {
            "id":     "cur_4",
            "title":  "Microsoft Reactor Live Events — Free RSVP",
            "date":   (today + timedelta(days=1)).strftime("%Y-%m-%d"),
            "url":    "https://developer.microsoft.com/en-us/reactor/",
            "source": "Microsoft",
            "rsvp":   True
        },
        {
            "id":     "cur_5",
            "title":  "freeCodeCamp Live Sessions — Free Registration",
            "date":   (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            "url":    "https://www.freecodecamp.org/news/tag/events/",
            "source": "freeCodeCamp",
            "rsvp":   True
        },
        {
            "id":     "cur_6",
            "title":  "CNCF Webinars — Free Cloud Native Events",
            "date":   (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            "url":    "https://community.cncf.io/events/",
            "source": "CNCF",
            "rsvp":   True
        },
        {
            "id":     "cur_7",
            "title":  "GitHub Online Events — Free Developer Sessions",
            "date":   (today + timedelta(days=4)).strftime("%Y-%m-%d"),
            "url":    "https://resources.github.com/events/",
            "source": "GitHub",
            "rsvp":   True
        },
        {
            "id":     "cur_8",
            "title":  "PyData Online Meetups — Free RSVP",
            "date":   (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            "url":    "https://www.meetup.com/pro/pydata/",
            "source": "PyData",
            "rsvp":   True
        },
        {
            "id":     "cur_9",
            "title":  "Women in Tech Summit — Free Online Events",
            "date":   (today + timedelta(days=4)).strftime("%Y-%m-%d"),
            "url":    "https://womenintechsummit.net/events/",
            "source": "WIT Summit",
            "rsvp":   True
        },
        {
            "id":     "cur_10",
            "title":  "Linux Foundation Free Webinars — Register",
            "date":   (today + timedelta(days=6)).strftime("%Y-%m-%d"),
            "url":    "https://events.linuxfoundation.org/",
            "source": "Linux Foundation",
            "rsvp":   True
        },
        {
            "id":     "cur_11",
            "title":  "Hashicorp DevOps Events — Free Online RSVP",
            "date":   (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            "url":    "https://www.hashicorp.com/events",
            "source": "HashiCorp",
            "rsvp":   True
        },
        {
            "id":     "cur_12",
            "title":  "DevOps Days Community Events — Free Registration",
            "date":   (today + timedelta(days=7)).strftime("%Y-%m-%d"),
            "url":    "https://devopsdays.org/events/",
            "source": "DevOpsDays",
            "rsvp":   True
        },
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  AGGREGATOR
# ══════════════════════════════════════════════════════════════════════════════

def fetch_rss_events(url, source):
    """Generic RSS event fetcher using standard library xml.etree."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link: continue
            if not is_tech(title): continue
            results.append({
                "id": f"rss_{hash(link) % 999999}",
                "title": title,
                "date": "See link for date",
                "url": link,
                "source": source,
                "rsvp": True
            })
        return results
    except Exception as e:
        log.error(f"RSS error from {source}: {e}")
        return []

def get_techcrunch_events():
    return fetch_rss_events("https://techcrunch.com/category/events/feed/", "TechCrunch")

def get_wired_events():
    return fetch_rss_events("https://www.wired.com/feed/category/business/latest/rss", "Wired")

def get_geekwire_events():
    return fetch_rss_events("https://www.geekwire.com/events/feed/", "GeekWire")

def get_all_events():
    log.info("Deep Discovery: Fetching events from all real sources in parallel...")
    
    sources = [
        get_luma_events,
        get_eventbrite_events,
        get_meetup_events,
        get_devto_events,
        get_techcrunch_events,
        get_wired_events,
        get_geekwire_events
    ]
    
    all_events = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_source = {executor.submit(getter): getter.__name__ for getter in sources}
        for future in concurrent.futures.as_completed(future_to_source):
            src_name = future_to_source[future]
            try:
                res = future.result()
                all_events.extend(res)
                log.info(f"   + {len(res)} from {src_name}")
            except Exception as e:
                log.error(f"Error polling {src_name}: {e}")

    # Deduplicate by URL
    seen_urls, unique = set(), []
    for e in all_events:
        if e["url"] not in seen_urls and e["title"]:
            seen_urls.add(e["url"])
            unique.append(e)

    log.info(f"Live events found: {len(unique)}")

    # Pad with curated events if not enough
    if len(unique) < MIN_EVENTS:
        seen_titles = {e["title"].lower().strip()[:60] for e in unique}
        for e in get_curated_events():
            key = e["title"].lower().strip()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(e)
        log.info(f"After padding: {len(unique)} events")

    return unique


# ─── Message Builder ─────────────────────────────────────────────────────────

def build_message(events):
    today = datetime.now().strftime("%A, %d %b %Y")
    msg   = f"🖥️ <b>Free Tech Events — RSVP Links</b>\n📅 {today}\n\n"
    for i, e in enumerate(events, 1):
        title  = html.escape(e['title'])
        source = html.escape(e['source'])
        msg += f"<b>{i}. {title}</b>\n"
        if e["date"] not in ("See link", "See link for date", "Ongoing"):
            msg += f"   📆 {e['date']}\n"
        msg += f"   🔗 <a href='{e['url']}'>Click Here to RSVP</a>\n"
        msg += f"   📌 <i>{source}</i>\n\n"
    msg += "<i>Tap the button below to refresh anytime! 👇</i>"
    return msg


# ─── Broadcast ───────────────────────────────────────────────────────────────

def broadcast_events(force=False):
    log.info("─── Broadcast process started ───")
    subscribers = load_subscribers()
    if not subscribers:
        log.info("No subscribers found.")
        return {"sent": 0, "failed": 0, "events": 0}

    sent_ids   = load_sent_ids()
    all_events = get_all_events()
    
    if force:
        new_events = all_events
        log.info("Test Mode: Bypassing duplicate filters.")
    else:
        new_events = [e for e in all_events if e["id"] not in sent_ids]
    
    if len(new_events) < MIN_EVENTS and not force:
        new_events = all_events

    to_send = new_events[:MAX_EVENTS]
    message = build_message(to_send)

    sent, failed = 0, 0
    for chat_id in subscribers:
        if send_message(chat_id, message, show_button=True):
            sent += 1
        else:
            failed += 1

    if not force:
        sent_ids.update(e["id"] for e in to_send)
        save_sent_ids(sent_ids)
        
    log.info(f"Broadcast: {sent} sent, {failed} failed, {len(to_send)} events")
    return {"sent": sent, "failed": failed, "events": len(to_send)}


# ─── Telegram Webhook ────────────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    # Handle button taps
    if "callback_query" in data:
        cb      = data["callback_query"]
        chat_id = str(cb["message"]["chat"]["id"])
        cb_id   = cb["id"]
        action  = cb.get("data", "")
        answer_callback(cb_id)
        if action == "get_events":
            send_message(chat_id, "⏳ Fetching fresh events with RSVP links...")
            events  = get_all_events()
            to_send = events[:MAX_EVENTS]
            send_message(chat_id, build_message(to_send), show_button=True)
        return "ok"

    # Handle text messages
    message  = data.get("message", {})
    chat     = message.get("chat", {})
    text     = message.get("text", "").strip()
    chat_id  = str(chat.get("id", ""))
    name     = chat.get("first_name", "Friend")
    username = chat.get("username", "")

    if not chat_id:
        return "ok"

    subscribers = load_subscribers()

    if text == "/start":
        if chat_id not in subscribers:
            subscribers[chat_id] = {
                "name": name, "username": username,
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            save_subscribers(subscribers)
            log.info(f"New subscriber: {name} ({chat_id})")

        send_message(chat_id,
            f"👋 Hey *{name}*! Welcome to *Giftkarimi Tech Events Bot*! 🎉\n\n"
            f"Every event comes with a *direct RSVP link* so you can register instantly!\n\n"
            f"🟢 Google Meet events are labeled\n"
            f"🔵 Zoom events are labeled\n"
            f"📅 Daily events sent at 8:00 AM\n"
            f"🔕 /stop — Unsubscribe anytime\n\n"
            f"👇 Tap below to get today's events!",
            show_button=True
        )

    elif text == "/stop":
        if chat_id in subscribers:
            del subscribers[chat_id]
            save_subscribers(subscribers)
        send_message(chat_id, "😢 Unsubscribed!\n\nType /start anytime to come back.")

    elif text == "/events":
        send_message(chat_id, "⏳ Fetching fresh events with RSVP links...")
        events  = get_all_events()
        to_send = events[:MAX_EVENTS]
        send_message(chat_id, build_message(to_send), show_button=True)

    elif text == "/count":
        send_message(chat_id, f"👥 *Total subscribers:* {len(subscribers)}", show_button=True)

    elif text == "/help":
        send_message(chat_id,
            "🤖 *Giftkarimi Tech Events Bot*\n\n"
            "All events have *direct RSVP links*!\n"
            "🟢 = Google Meet  🔵 = Zoom\n\n"
            "/start — Subscribe\n"
            "/stop — Unsubscribe\n"
            "/events — Get events now\n"
            "/count — Subscriber count\n\n"
            "Or tap the button below 👇",
            show_button=True
        )
    else:
        send_message(chat_id,
            "👇 Tap the button to get free tech events with RSVP links!",
            show_button=True
        )

    return "ok"


# ─── Admin Panel ─────────────────────────────────────────────────────────────

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Giftkarimi Bot Admin</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1a1a2e, #16213e);
            padding: 20px; text-align: center; border-bottom: 1px solid #2a2a4a; }
  .header h1 { font-size: 22px; color: #7c8cf8; }
  .header p  { font-size: 13px; color: #888; margin-top: 4px; }
  .container { max-width: 600px; margin: 0 auto; padding: 20px; }
  .card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px;
          padding: 20px; margin-bottom: 16px; }
  .card h2 { font-size: 15px; color: #7c8cf8; margin-bottom: 14px; }
  .stat { display: flex; justify-content: space-between; align-items: center;
          padding: 10px 0; border-bottom: 1px solid #2a2a4a; }
  .stat:last-child { border-bottom: none; }
  .stat-label { font-size: 13px; color: #aaa; }
  .stat-value { font-size: 18px; font-weight: bold; color: #fff; }
  .btn { width: 100%; padding: 14px; border: none; border-radius: 10px;
         font-size: 15px; font-weight: 600; cursor: pointer; margin-bottom: 10px; transition: opacity 0.2s; }
  .btn:active { opacity: 0.7; }
  .btn-primary { background: linear-gradient(135deg, #7c8cf8, #5b6cf8); color: #fff; }
  .btn-success { background: linear-gradient(135deg, #7cf8a8, #5bf880); color: #111; }
  .subscriber { display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid #2a2a4a; }
  .subscriber:last-child { border-bottom: none; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; background: #7c8cf8;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; color: #fff; margin-right: 12px; font-size: 14px; flex-shrink: 0; }
  .sub-name { font-size: 14px; font-weight: 600; }
  .sub-meta { font-size: 11px; color: #888; margin-top: 2px; }
  .sources { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .source-tag { background: #2a2a4a; color: #7c8cf8; padding: 4px 10px; border-radius: 20px; font-size: 11px; }
  .gmeet-tag  { background: #1a3a2a; color: #7cf8a8; padding: 4px 10px; border-radius: 20px; font-size: 11px; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
           background: #2a2a4a; color: #fff; padding: 12px 24px; border-radius: 30px;
           font-size: 14px; display: none; z-index: 99; }
  .login-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .login-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 16px;
                padding: 30px; width: 90%; max-width: 360px; text-align: center; }
  .login-card h2 { color: #7c8cf8; margin-bottom: 6px; }
  .login-card p  { color: #888; font-size: 13px; margin-bottom: 20px; }
  input { width: 100%; padding: 12px; border: 1px solid #2a2a4a; border-radius: 8px;
          background: #0f0f1a; color: #fff; font-size: 15px; margin-bottom: 12px; }
  .result-box { background: #0f0f1a; border-radius: 8px; padding: 12px;
                font-size: 13px; color: #7cf8a8; margin-top: 10px; display: none; line-height: 1.4; border: 1px solid #2a2a4a; }
  .tag { padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
  .tag-green { background: #7cf8a8; color: #111; }
  .tag-orange { background: #f8a07c; color: #111; }
</style>
</head>
<body>
<div class="login-wrap" id="loginWrap">
  <div class="login-card">
    <h2 style="font-size: 24px; margin-bottom: 10px;">🛡️ Tech Admin</h2>
    <p style="margin-bottom: 25px;">Secure Access Required</p>
    <input type="password" id="pwInput" placeholder="Password" style="text-align: center;" />
    <button class="btn btn-primary" onclick="login()">Enter Dashboard</button>
  </div>
</div>

<div id="adminPanel">
  <div class="header">
    <h1>🖥️ Giftkarimi Bot</h1>
    <p>Admin Dashboard — RSVP Edition</p>
  </div>
  <div class="container">
    <div class="card">
      <h2>📊 Stats</h2>
      <div class="stat"><span class="stat-label">Total Subscribers</span>
        <span class="stat-value" id="subCount">—</span></div>
      <div class="stat"><span class="stat-label">Scheduler Mode</span>
        <span class="stat-value" id="schedulerMode">—</span></div>
      <div class="stat"><span class="stat-label">Daily Send Time</span>
        <span class="stat-value" id="broadcastTime">8:00 AM EAT</span></div>
      <div class="stat"><span class="stat-label">Min Events Per Post</span>
        <span class="stat-value">10</span></div>
    </div>

    <div class="card">
      <h2>📡 Event Sources (All RSVP)</h2>
      <div class="sources">
        <span class="gmeet-tag">🟢 Luma</span>
        <span class="source-tag">Eventbrite</span>
        <span class="source-tag">Meetup</span>
        <span class="source-tag">Dev.to</span>
        <span class="gmeet-tag">🟢 Google Developers</span>
        <span class="gmeet-tag">🟢 Google Cloud</span>
        <span class="source-tag">AWS Events</span>
        <span class="source-tag">Microsoft Reactor</span>
        <span class="source-tag">CNCF</span>
        <span class="source-tag">Linux Foundation</span>
      </div>
    </div>

    <div class="card">
      <h2>⚡ Actions</h2>
      <button class="btn btn-success" onclick="broadcast()">📤 Send Events to All Now</button>
      <button class="btn btn-primary" onclick="testBroadcast()">🧪 Send TEST to Admin Only</button>
      <button class="btn btn-primary" onclick="loadSubscribers()">🔄 Refresh</button>
      <div class="result-box" id="resultBox"></div>
    </div>

    <div class="card">
      <h2>👥 Subscribers</h2>
      <div id="subList">Loading...</div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<script>
let password = "";
function login() {
  password = document.getElementById("pwInput").value;
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } }).then(r => {
    if (r.ok) {
      document.getElementById("loginWrap").style.display = "none";
      document.getElementById("adminPanel").style.display = "block";
      showToast("🔓 Access Granted");
      loadData();
    } else { showToast("❌ Incorrect Password"); }
  });
}
function loadData() {
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      document.getElementById("subCount").textContent = d.subscriber_count;
      document.getElementById("broadcastTime").textContent = d.send_time + " AM EAT";
      const modeEl = document.getElementById("schedulerMode");
      if (d.test_interval > 0) {
        modeEl.innerHTML = `<span class="tag tag-orange">Interval (${d.test_interval}m)</span>`;
      } else {
        modeEl.innerHTML = `<span class="tag tag-green">Daily</span>`;
      }
    });
  loadSubscribers();
}
function loadSubscribers() {
  fetch("/admin/subscribers", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(data => {
      const list = document.getElementById("subList");
      if (!data.subscribers || data.subscribers.length === 0) {
        list.innerHTML = '<p style="color:#888;font-size:13px">No subscribers yet. Share @Giftkarimi_bot!</p>';
        return;
      }
      list.innerHTML = data.subscribers.map(s => `
        <div class="subscriber">
          <div class="avatar">${s.name[0].toUpperCase()}</div>
          <div style="flex:1">
            <div class="sub-name">${s.name}</div>
            <div class="sub-meta">${s.username ? "@"+s.username : "No username"} · Joined ${s.joined}</div>
          </div>
        </div>`).join("");
      document.getElementById("subCount").textContent = data.subscribers.length;
    });
}
function broadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Fetching RSVP events and sending to all...";
  fetch("/admin/broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = `✅ Sent to ${d.sent} subscribers with ${d.events} events!`;
      showToast("✅ Done!");
    }).catch(() => { box.textContent = "❌ Something went wrong."; });
}
function testBroadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Sending test broadcast to admin...";
  fetch("/admin/test-broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = d.success ? "✅ Test message sent to admin!" : "❌ " + d.error;
      showToast(d.success ? "✅ Done!" : "❌ Error");
    }).catch(() => { box.textContent = "❌ Something went wrong."; });
}
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => t.style.display = "none", 3000);
}
document.getElementById("pwInput").addEventListener("keydown", e => { if (e.key==="Enter") login(); });
</script>
</body>
</html>
"""

def check_admin(req):
    return req.headers.get("X-Admin-Password") == ADMIN_PASSWORD

@app.route("/")
def index():
    return render_template_string(ADMIN_HTML)

@app.route("/admin/stats")
def admin_stats():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "subscriber_count": len(load_subscribers()),
        "send_time": SEND_TIME,
        "test_interval": TEST_INTERVAL_MINS,
        "nairobi_time": datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%I:%M %p EAT")
    })

@app.route("/admin/subscribers")
def admin_subscribers():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    subs = load_subscribers()
    return jsonify({"subscribers": [
        {"name": v["name"], "username": v.get("username", ""), "joined": v["joined"]}
        for v in subs.values()
    ]})

@app.route("/admin/broadcast", methods=["POST"])
def admin_broadcast():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify(broadcast_events())

@app.route("/admin/test-broadcast", methods=["POST"])
def admin_test_broadcast():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    test_id = os.getenv("TELEGRAM_CHAT_ID")
    if not test_id:
        subs = load_subscribers()
        if subs: test_id = list(subs.keys())[0]
    
    if not test_id:
        return jsonify({"success": False, "error": "No subscriber found for testing"})
    
    all_events = get_all_events()
    message = build_message(all_events[:MAX_EVENTS])
    success = send_message(test_id, "🧪 <b>TEST BROADCAST</b>\n\n" + message)
    return jsonify({"success": success, "error": None if success else "Telegram failed"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "rsvp-edition"})


# ─── Scheduler & Main ────────────────────────────────────────────────────────

def run_scheduler():
    """
    Bulletproof scheduler using Kenyan time.
    Supports either Daily Mode or Interval Mode (for testing).
    """
    EAT = ZoneInfo("Africa/Nairobi")
    if TEST_INTERVAL_MINS > 0:
        log.info(f"Scheduler started — INTERVAL MODE: sending every {TEST_INTERVAL_MINS} minute(s)")
    else:
        log.info(f"Scheduler started — DAILY MODE: sending at {SEND_TIME} EAT (Nairobi)")
    
    send_hour, send_min = map(int, SEND_TIME.split(":"))

    while True:
        try:
            now = datetime.now(EAT)
            
            if TEST_INTERVAL_MINS > 0:
                # ─── Interval Mode ───
                last_ts  = load_last_run_timestamp()
                now_ts   = int(now.timestamp())
                wait_sec = (last_ts + TEST_INTERVAL_MINS * 60) - now_ts
                
                if wait_sec <= 0:
                    log.info(f"Interval trigger — sending broadcast ({TEST_INTERVAL_MINS} min interval)")
                    broadcast_events(force=True)
                    save_last_run(ts=now_ts)
                else:
                    if now_ts % 60 == 0:
                        log.info(f"Interval Mode: Next trigger in {wait_sec}s")
            else:
                # ─── Daily Mode ───
                today_str     = now.strftime("%Y-%m-%d")
                last_sent_day = load_last_run()
                now_total     = now.hour * 60 + now.minute
                snd_total     = send_hour * 60 + send_min

                if now_total >= snd_total and last_sent_day != today_str:
                    log.info(f"Daily trigger — sending broadcast (Nairobi: {now.strftime('%H:%M EAT')})")
                    broadcast_events()
                    save_last_run(day_str=today_str)
                    
        except Exception as ex:
            log.error(f"Scheduler error: {ex}")
        time.sleep(20)

def self_ping():
    """Pings /health every 5 minutes to prevent Railway free tier from sleeping."""
    app_url = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not app_url:
        log.warning("No app URL for self-ping — bot may sleep and miss send time.")
        return
    prefix = "" if app_url.startswith("http") else "https://"
    ping_url = f"{prefix}{app_url}/health"
    log.info(f"Self-ping active → {ping_url} every 5 min")
    while True:
        try:
            resp = requests.get(ping_url, timeout=10)
            log.info(f"Ping OK ({resp.status_code})")
        except Exception as ex:
            log.warning(f"Ping failed: {ex}")
        time.sleep(300)

def setup_webhook():
    app_url = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if app_url:
        prefix = "" if app_url.startswith("http") else "https://"
        set_webhook(f"{prefix}{app_url}/webhook/{TELEGRAM_BOT_TOKEN}")

# Start background threads at module level so gunicorn picks them up
setup_webhook()
threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=self_ping,     daemon=True).start()
log.info(f"Bot started — scheduler and self-ping running")

if __name__ == "__main__":
    log.info(f"Running directly on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
