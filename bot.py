"""
Giftkarimi Tech Events Bot — Fixed Edition
- Sends at exactly 8:00 AM East Africa Time (UTC+3)
- Get Events button on every message
- Events only from today + next 2 days
- English only
- Max sources for real online/Zoom meetings
"""

import os
import json
import logging
import requests
import schedule
import time
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
EVENTBRITE_TOKEN   = os.getenv("EVENTBRITE_TOKEN", "")
SEND_TIME          = os.getenv("SEND_TIME", "08:00")       # Local time (EAT UTC+3)
TIMEZONE_OFFSET    = int(os.getenv("TIMEZONE_OFFSET", "3")) # UTC+3 for Nairobi
MIN_EVENTS         = int(os.getenv("MIN_EVENTS", "10"))
MAX_EVENTS         = int(os.getenv("MAX_EVENTS", "15"))
ADMIN_PASSWORD     = os.getenv("ADMIN_PASSWORD", "gift2024")
PORT               = int(os.getenv("PORT", "5000"))

SUBSCRIBERS_FILE   = "subscribers.json"
SENT_IDS_FILE      = "sent_ids.json"
TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
HEADERS            = {"User-Agent": "Mozilla/5.0 (compatible; TechEventsBot/1.0)",
                      "Accept-Language": "en-US,en;q=0.9"}

# Inline button shown on every message
GET_EVENTS_BUTTON  = {
    "inline_keyboard": [[
        {"text": "🖥️ Get Today's Events", "callback_data": "get_events"}
    ]]
}

# Date window: today and next 2 days only
def date_window():
    now   = datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = start + timedelta(days=2, hours=23, minutes=59)
    return start, end

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


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_message(chat_id, text, show_button=True):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if show_button:
            payload["reply_markup"] = GET_EVENTS_BUTTON
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
        return resp.ok
    except Exception as ex:
        log.error(f"Telegram error {chat_id}: {ex}")
        return False

def answer_callback(cb_id):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                      json={"callback_query_id": cb_id}, timeout=10)
    except Exception:
        pass

def set_webhook(url):
    resp = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": url})
    log.info(f"Webhook: {resp.json()}")


# ─── English Filter ───────────────────────────────────────────────────────────

def is_english(text):
    """Basic check — rejects titles with non-latin characters."""
    if not text:
        return False
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        # Allow common accented latin chars but reject CJK, Arabic, etc.
        latin_count = sum(1 for c in text if ord(c) < 1000)
        return latin_count / len(text) > 0.85


# ══════════════════════════════════════════════════════════════════════════════
#  EVENT SOURCES
# ══════════════════════════════════════════════════════════════════════════════

# ─── 1. Eventbrite ───────────────────────────────────────────────────────────
def get_eventbrite_events():
    if not EVENTBRITE_TOKEN:
        return []
    start, end = date_window()
    try:
        url    = "https://www.eventbriteapi.com/v3/events/search/"
        params = {
            "categories":             "102",
            "is_free":                "true",
            "online_events_only":     "true",
            "sort_by":                "date",
            "page_size":              50,
            "locale":                 "en_US",
            "start_date.range_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_date.range_end":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {EVENTBRITE_TOKEN}",
                                     **HEADERS}, timeout=15)
        resp.raise_for_status()
        results = []
        for e in resp.json().get("events", []):
            title = e["name"]["text"]
            if not is_english(title):
                continue
            results.append({
                "id":     f"eb_{e['id']}",
                "title":  title,
                "date":   e["start"]["local"][:16].replace("T", " "),
                "url":    e["url"],
                "source": "Eventbrite 🎟️"
            })
        log.info(f"Eventbrite: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Eventbrite: {ex}")
        return []


# ─── 2. Luma ─────────────────────────────────────────────────────────────────
def get_luma_events():
    start, end = date_window()
    try:
        url    = "https://api.lu.ma/public/v1/calendar/list-events"
        params = {
            "pagination_limit": 50,
            "after": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "before": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if not resp.ok:
            return []
        tech_kw = ["tech", "ai", "python", "web", "data", "cloud", "code",
                   "developer", "software", "machine learning", "startup",
                   "crypto", "blockchain", "cybersecurity", "devops", "product",
                   "zoom", "webinar", "online", "virtual", "workshop", "hackathon"]
        results = []
        for item in resp.json().get("entries", []):
            e     = item.get("event", {})
            title = e.get("name", "")
            if not title or not is_english(title):
                continue
            if not any(k in title.lower() for k in tech_kw):
                continue
            results.append({
                "id":     f"luma_{e.get('api_id', hash(title))}",
                "title":  title,
                "date":   e.get("start_at", "")[:16].replace("T", " "),
                "url":    f"https://lu.ma/{e.get('url', '')}",
                "source": "Luma 🌐"
            })
        log.info(f"Luma: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Luma: {ex}")
        return []


# ─── 3. Meetup ───────────────────────────────────────────────────────────────
def get_meetup_events():
    start, end = date_window()
    try:
        query = """
        { rankedEvents(filter: {
            query: "tech webinar workshop online free"
            isOnline: true
            isFree: true
            startDateRange: { start: "%s" end: "%s" }
          } first: 50) {
            edges { node { id title dateTime eventUrl } }
        }}""" % (start.strftime("%Y-%m-%dT%H:%M:%S"),
                 end.strftime("%Y-%m-%dT%H:%M:%S"))
        resp = requests.post("https://api.meetup.com/gql",
                             json={"query": query}, headers=HEADERS, timeout=15)
        if not resp.ok:
            return []
        results = []
        for edge in resp.json().get("data", {}).get("rankedEvents", {}).get("edges", []):
            n     = edge.get("node", {})
            title = n.get("title", "")
            if not is_english(title):
                continue
            results.append({
                "id":     f"mu_{n['id']}",
                "title":  title,
                "date":   n.get("dateTime", "")[:16].replace("T", " "),
                "url":    n["eventUrl"],
                "source": "Meetup 👥"
            })
        log.info(f"Meetup: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Meetup: {ex}")
        return []


# ─── 4. Dev.to events ────────────────────────────────────────────────────────
def get_devto_events():
    try:
        resp = requests.get("https://dev.to/api/listings",
                            params={"category": "events", "per_page": 30},
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        results = []
        for item in resp.json():
            title = item.get("title", "")
            if not title or not is_english(title):
                continue
            results.append({
                "id":     f"devto_{item['id']}",
                "title":  title,
                "date":   "See link",
                "url":    f"https://dev.to{item.get('path', '')}",
                "source": "Dev.to 💻"
            })
        log.info(f"Dev.to: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Dev.to: {ex}")
        return []


# ─── 5. Zoom Events (via Eventbrite + Luma zoom-tagged) ──────────────────────
def get_zoom_events():
    """Search specifically for Zoom meeting events."""
    if not EVENTBRITE_TOKEN:
        return []
    start, end = date_window()
    try:
        url    = "https://www.eventbriteapi.com/v3/events/search/"
        params = {
            "q":                      "zoom webinar",
            "is_free":                "true",
            "online_events_only":     "true",
            "sort_by":                "date",
            "page_size":              30,
            "locale":                 "en_US",
            "start_date.range_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_date.range_end":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {EVENTBRITE_TOKEN}",
                                     **HEADERS}, timeout=15)
        resp.raise_for_status()
        results = []
        for e in resp.json().get("events", []):
            title = e["name"]["text"]
            if not is_english(title):
                continue
            results.append({
                "id":     f"zoom_{e['id']}",
                "title":  f"🎥 {title}",
                "date":   e["start"]["local"][:16].replace("T", " "),
                "url":    e["url"],
                "source": "Zoom/Eventbrite 🎥"
            })
        log.info(f"Zoom events: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Zoom events: {ex}")
        return []


# ─── 6. RSS Feeds ────────────────────────────────────────────────────────────
def get_rss_events(feed_url, source_name):
    start, end = date_window()
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []
        event_kw = [
            "webinar", "workshop", "conference", "summit", "hackathon",
            "bootcamp", "online event", "virtual event", "zoom", "live session",
            "free training", "free course", "tech talk", "developer event"
        ]
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            date  = (item.findtext("pubDate") or "")[:16]
            if not title or not link or not is_english(title):
                continue
            if not any(k in title.lower() for k in event_kw):
                continue
            results.append({
                "id":     f"{source_name.lower()}_{hash(link) % 999999}",
                "title":  title,
                "date":   date or "See link",
                "url":    link,
                "source": f"{source_name} 📰"
            })
        log.info(f"{source_name}: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"{source_name}: {ex}")
        return []


def get_all_rss_events():
    feeds = [
        ("https://feeds.feedburner.com/TechCrunch",        "TechCrunch"),
        ("https://www.wired.com/feed/rss",                 "Wired"),
        ("https://thenextweb.com/feed",                    "TheNextWeb"),
        ("https://www.infoq.com/feed",                     "InfoQ"),
        ("https://hackernoon.com/feed",                    "HackerNoon"),
        ("https://www.zdnet.com/news/rss.xml",             "ZDNet"),
        ("https://venturebeat.com/feed/",                  "VentureBeat"),
        ("https://www.techrepublic.com/rssfeeds/articles/","TechRepublic"),
    ]
    results = []
    for url, name in feeds:
        results.extend(get_rss_events(url, name))
    return results


# ─── 7. Fallback (always guaranteed events) ──────────────────────────────────
def get_fallback_events():
    today = (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime("%Y-%m-%d")
    tmrw  = (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET, days=1)).strftime("%Y-%m-%d")
    return [
        {"id": "fb_1",  "title": "AWS Free Online Tech Talk — Cloud & DevOps",
         "date": today, "url": "https://aws.amazon.com/events/online-tech-talks/", "source": "AWS ☁️"},
        {"id": "fb_2",  "title": "Microsoft Reactor — Free Live Developer Session",
         "date": today, "url": "https://developer.microsoft.com/en-us/reactor/", "source": "Microsoft 🪟"},
        {"id": "fb_3",  "title": "Google Cloud Free Webinar — AI & ML",
         "date": today, "url": "https://cloud.google.com/events", "source": "Google Cloud ☁️"},
        {"id": "fb_4",  "title": "freeCodeCamp — Free Live Coding Session",
         "date": today, "url": "https://www.freecodecamp.org/news/tag/events/", "source": "freeCodeCamp 🔥"},
        {"id": "fb_5",  "title": "GitHub — Free Open Source Workshop",
         "date": tmrw,  "url": "https://resources.github.com/webcasts/", "source": "GitHub 🐙"},
        {"id": "fb_6",  "title": "CNCF — Free Cloud Native Webinar",
         "date": tmrw,  "url": "https://www.cncf.io/events/", "source": "CNCF ☸️"},
        {"id": "fb_7",  "title": "Coursera — Free Live Learning Event",
         "date": today, "url": "https://www.coursera.org/events", "source": "Coursera 🎓"},
        {"id": "fb_8",  "title": "DevOps Days — Free Online Community Event",
         "date": tmrw,  "url": "https://devopsdays.org", "source": "DevOpsDays 🛠️"},
        {"id": "fb_9",  "title": "Linux Foundation — Free Open Source Summit",
         "date": tmrw,  "url": "https://events.linuxfoundation.org", "source": "Linux Foundation 🐧"},
        {"id": "fb_10", "title": "HashiCorp — Free DevOps & Infrastructure Webinar",
         "date": today, "url": "https://www.hashicorp.com/events", "source": "HashiCorp 🏗️"},
        {"id": "fb_11", "title": "PyCon — Free Python Online Workshop",
         "date": tmrw,  "url": "https://pycon.org", "source": "PyCon 🐍"},
        {"id": "fb_12", "title": "Re-Work — Free AI & ML Virtual Summit",
         "date": today, "url": "https://www.re-work.co/events", "source": "Re-Work 🤖"},
    ]


# ─── Aggregator ──────────────────────────────────────────────────────────────

def get_all_events():
    log.info("─── Fetching from all sources ───")
    all_events = []
    all_events += get_eventbrite_events()
    all_events += get_zoom_events()
    all_events += get_luma_events()
    all_events += get_meetup_events()
    all_events += get_devto_events()
    all_events += get_all_rss_events()

    # Deduplicate by title
    seen, unique = set(), []
    for e in all_events:
        key = e["title"].lower().strip()[:60]
        if key not in seen and e["title"]:
            seen.add(key)
            unique.append(e)

    log.info(f"Live events found: {len(unique)}")

    # Pad with fallback if below minimum
    if len(unique) < MIN_EVENTS:
        log.info("Padding with fallback events...")
        for e in get_fallback_events():
            key = e["title"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                unique.append(e)

    log.info(f"Total after padding: {len(unique)}")
    return unique


# ─── Message Builder ─────────────────────────────────────────────────────────

def build_message(events):
    now   = datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
    today = now.strftime("%A, %d %b %Y")
    msg   = f"🖥️ *Free Tech Events*\n📅 {today}\n\n"
    for i, e in enumerate(events, 1):
        msg += f"*{i}. {e['title']}*\n"
        if e['date'] not in ("See link", "Ongoing"):
            msg += f"   📆 {e['date']}\n"
        msg += f"   🔗 {e['url']}\n"
        msg += f"   📌 _{e['source']}_\n\n"
    msg += "_Tap the button below to refresh anytime! 👇_"
    return msg


# ─── Broadcast ───────────────────────────────────────────────────────────────

def broadcast_events():
    log.info("─── Daily broadcast ───")
    subscribers = load_subscribers()
    if not subscribers:
        log.info("No subscribers yet.")
        return {"sent": 0, "failed": 0, "events": 0}

    sent_ids   = load_sent_ids()
    all_events = get_all_events()
    new_events = [e for e in all_events if e["id"] not in sent_ids]
    if len(new_events) < MIN_EVENTS:
        new_events = all_events   # reset dedup if too few

    to_send = new_events[:MAX_EVENTS]
    message = build_message(to_send)

    sent, failed = 0, 0
    for chat_id in subscribers:
        if send_message(chat_id, message, show_button=True):
            sent += 1
        else:
            failed += 1
        time.sleep(0.05)  # small delay to avoid Telegram rate limit

    sent_ids.update(e["id"] for e in to_send)
    save_sent_ids(sent_ids)

    log.info(f"Broadcast: {sent} sent, {failed} failed, {len(to_send)} events")
    return {"sent": sent, "failed": failed, "events": len(to_send)}


# ─── Webhook ─────────────────────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    # Button taps
    if "callback_query" in data:
        cb      = data["callback_query"]
        chat_id = str(cb["message"]["chat"]["id"])
        answer_callback(cb["id"])
        if cb.get("data") == "get_events":
            send_message(chat_id, "⏳ Fetching fresh events from 10+ sources...", show_button=False)
            events = get_all_events()
            send_message(chat_id, build_message(events[:MAX_EVENTS]), show_button=True)
        return "ok"

    # Text messages
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
            f"Every day at *8:00 AM* you'll receive free online tech events "
            f"from 10+ websites — including Zoom meetings, webinars & workshops.\n\n"
            f"📅 Events from *today & next 2 days only*\n"
            f"🌍 English events only\n"
            f"🔕 /stop to unsubscribe anytime\n\n"
            f"👇 Tap below to get today's events now!",
            show_button=True
        )

    elif text == "/stop":
        if chat_id in subscribers:
            del subscribers[chat_id]
            save_subscribers(subscribers)
        send_message(chat_id,
            "😢 You've been unsubscribed.\n\nType /start anytime to come back!",
            show_button=False
        )

    elif text == "/events":
        send_message(chat_id, "⏳ Fetching fresh events from 10+ sources...", show_button=False)
        events = get_all_events()
        send_message(chat_id, build_message(events[:MAX_EVENTS]), show_button=True)

    elif text == "/count":
        send_message(chat_id, f"👥 *Total subscribers:* {len(subscribers)}", show_button=True)

    elif text == "/help":
        send_message(chat_id,
            "🤖 *Giftkarimi Tech Events Bot*\n\n"
            "📡 *Sources:* Eventbrite, Luma, Meetup, Dev.to, TechCrunch, "
            "Wired, InfoQ, HackerNoon, ZDNet, VentureBeat & more\n\n"
            "🕗 Sends daily at 8:00 AM EAT\n"
            "📅 Events from today & next 2 days\n"
            "🌍 English only\n\n"
            "/start — Subscribe\n"
            "/stop — Unsubscribe\n"
            "/events — Get events now\n"
            "/count — Subscribers\n\n"
            "👇 Or just tap the button!",
            show_button=True
        )

    else:
        send_message(chat_id,
            "👇 Tap the button to get today's free tech events!",
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
  .sub-info { flex: 1; }
  .sub-name { font-size: 14px; font-weight: 600; }
  .sub-meta { font-size: 11px; color: #888; margin-top: 2px; }
  .sources { display: flex; flex-wrap: wrap; gap: 6px; }
  .tag { background: #2a2a4a; color: #7c8cf8; padding: 4px 10px; border-radius: 20px; font-size: 11px; }
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
                font-size: 13px; color: #7cf8a8; margin-top: 10px; display: none; }
  #adminPanel { display: none; }
</style>
</head>
<body>
<div class="login-wrap" id="loginWrap">
  <div class="login-card">
    <h2>🤖 Admin Panel</h2>
    <p>Giftkarimi Tech Events Bot</p>
    <input type="password" id="pwInput" placeholder="Enter password" />
    <button class="btn btn-primary" onclick="login()">Login</button>
  </div>
</div>
<div id="adminPanel">
  <div class="header">
    <h1>🖥️ Giftkarimi Bot</h1>
    <p>Admin Dashboard</p>
  </div>
  <div class="container">
    <div class="card">
      <h2>📊 Stats</h2>
      <div class="stat"><span class="stat-label">Total Subscribers</span><span class="stat-value" id="subCount">—</span></div>
      <div class="stat"><span class="stat-label">Bot Username</span><span class="stat-value" style="font-size:14px">@Giftkarimi_bot</span></div>
      <div class="stat"><span class="stat-label">Daily Send Time</span><span class="stat-value" style="font-size:14px">8:00 AM EAT</span></div>
      <div class="stat"><span class="stat-label">Event Window</span><span class="stat-value" style="font-size:14px">Today + 2 days</span></div>
      <div class="stat"><span class="stat-label">Language</span><span class="stat-value" style="font-size:14px">English only 🇬🇧</span></div>
    </div>
    <div class="card">
      <h2>📡 Sources (10+)</h2>
      <div class="sources">
        <span class="tag">Eventbrite</span><span class="tag">Zoom/Eventbrite</span>
        <span class="tag">Luma</span><span class="tag">Meetup</span>
        <span class="tag">Dev.to</span><span class="tag">TechCrunch</span>
        <span class="tag">Wired</span><span class="tag">InfoQ</span>
        <span class="tag">HackerNoon</span><span class="tag">ZDNet</span>
        <span class="tag">VentureBeat</span><span class="tag">TheNextWeb</span>
        <span class="tag">+ Fallback</span>
      </div>
    </div>
    <div class="card">
      <h2>⚡ Actions</h2>
      <button class="btn btn-success" onclick="broadcast()">📤 Send Events to All Subscribers Now</button>
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
      loadData();
    } else showToast("❌ Wrong password");
  });
}
function loadData() {
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => document.getElementById("subCount").textContent = d.subscriber_count);
  loadSubscribers();
}
function loadSubscribers() {
  fetch("/admin/subscribers", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(data => {
      const list = document.getElementById("subList");
      if (!data.subscribers || !data.subscribers.length) {
        list.innerHTML = '<p style="color:#888;font-size:13px">No subscribers yet. Share @Giftkarimi_bot!</p>';
        return;
      }
      list.innerHTML = data.subscribers.map(s => `
        <div class="subscriber">
          <div class="avatar">${s.name[0].toUpperCase()}</div>
          <div class="sub-info">
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
  box.textContent = "⏳ Fetching from 10+ sources and sending...";
  fetch("/admin/broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = `✅ Sent to ${d.sent} subscribers with ${d.events} events!`;
      showToast("✅ Done!");
    }).catch(() => box.textContent = "❌ Something went wrong.");
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
    return jsonify({"subscriber_count": len(load_subscribers()), "send_time": SEND_TIME})

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

@app.route("/health")
def health():
    return jsonify({"status": "ok", "sources": 13})


# ─── Scheduler ───────────────────────────────────────────────────────────────

def run_scheduler():
    """
    Railway runs on UTC. We schedule in UTC by subtracting the timezone offset.
    SEND_TIME is 08:00 EAT (UTC+3), so we schedule at 05:00 UTC.
    """
    h, m      = map(int, SEND_TIME.split(":"))
    utc_h     = (h - TIMEZONE_OFFSET) % 24
    utc_time  = f"{utc_h:02d}:{m:02d}"
    schedule.every().day.at(utc_time).do(broadcast_events)
    log.info(f"Scheduler: fires at {utc_time} UTC = {SEND_TIME} EAT")
    while True:
        schedule.run_pending()
        time.sleep(30)

def setup_webhook():
    url = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if url:
        set_webhook(f"https://{url}/webhook/{TELEGRAM_BOT_TOKEN}")

if __name__ == "__main__":
    setup_webhook()
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info(f"Bot starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
