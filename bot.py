"""
Giftkarimi Tech Events Bot
- Friends subscribe via Telegram (@Giftkarimi_bot)
- Free tech events sent daily to all subscribers
- Web admin panel to manage subscribers
"""

import os
import json
import logging
import requests
import schedule
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8245478915:AAG_yyJHuX7D_yorjENkwjPSoqrkQEaB4zA")
EVENTBRITE_TOKEN   = os.getenv("EVENTBRITE_TOKEN", "")
SEND_TIME          = os.getenv("SEND_TIME", "08:00")
MAX_EVENTS         = int(os.getenv("MAX_EVENTS", "10"))
ADMIN_PASSWORD     = os.getenv("ADMIN_PASSWORD", "gift2024")
PORT               = int(os.getenv("PORT", "5000"))

SUBSCRIBERS_FILE   = "subscribers.json"
SENT_IDS_FILE      = "sent_ids.json"

TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = Flask(__name__)


# ─── Subscriber Storage ───────────────────────────────────────────────────────

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


# ─── Telegram Helpers ─────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": parse_mode
        }, timeout=15)
        return resp.ok
    except Exception as ex:
        log.error(f"Send error to {chat_id}: {ex}")
        return False

def set_webhook(webhook_url):
    resp = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
    log.info(f"Webhook set: {resp.json()}")


# ─── Eventbrite ──────────────────────────────────────────────────────────────

def get_eventbrite_events():
    if not EVENTBRITE_TOKEN:
        log.warning("No EVENTBRITE_TOKEN — using mock events for now.")
        return get_mock_events()

    url    = "https://www.eventbriteapi.com/v3/events/search/"
    params = {
        "categories":             "102",
        "is_free":                "true",
        "online_events_only":     "true",
        "sort_by":                "date",
        "start_date.range_start": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_date.range_end":   (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_size":              50,
    }
    headers = {"Authorization": f"Bearer {EVENTBRITE_TOKEN}"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        events  = resp.json().get("events", [])
        results = []
        for e in events:
            results.append({
                "id":     f"eb_{e['id']}",
                "title":  e["name"]["text"],
                "date":   e["start"]["local"][:16].replace("T", " "),
                "url":    e["url"],
                "source": "Eventbrite"
            })
        log.info(f"Eventbrite: {len(results)} events.")
        return results
    except Exception as ex:
        log.error(f"Eventbrite error: {ex}")
        return get_mock_events()

def get_mock_events():
    """Sample events shown when no API token is set."""
    today = datetime.now()
    return [
        {
            "id":     "mock_1",
            "title":  "Introduction to AI & Machine Learning",
            "date":   (today + timedelta(days=1)).strftime("%Y-%m-%d 10:00"),
            "url":    "https://eventbrite.com",
            "source": "Sample"
        },
        {
            "id":     "mock_2",
            "title":  "Web Development with React — Free Workshop",
            "date":   (today + timedelta(days=2)).strftime("%Y-%m-%d 14:00"),
            "url":    "https://eventbrite.com",
            "source": "Sample"
        },
        {
            "id":     "mock_3",
            "title":  "Python for Beginners — Live Session",
            "date":   (today + timedelta(days=3)).strftime("%Y-%m-%d 18:00"),
            "url":    "https://eventbrite.com",
            "source": "Sample"
        },
    ]


# ─── Broadcast ───────────────────────────────────────────────────────────────

def build_events_message(events):
    today = datetime.now().strftime("%A, %d %b %Y")
    msg   = f"🖥️ *Free Tech Events*\n📅 {today}\n\n"
    for i, e in enumerate(events, 1):
        msg += f"*{i}. {e['title']}*\n"
        msg += f"   📆 {e['date']}\n"
        msg += f"   🔗 {e['url']}\n"
        msg += f"   📌 _{e['source']}_\n\n"
    msg += "_Type /stop anytime to unsubscribe._"
    return msg

def broadcast_events():
    log.info("─── Broadcasting daily events ───")
    subscribers = load_subscribers()

    if not subscribers:
        log.info("No subscribers yet.")
        return {"sent": 0, "failed": 0}

    sent_ids   = load_sent_ids()
    all_events = get_eventbrite_events()
    new_events = [e for e in all_events if e["id"] not in sent_ids]

    if not new_events:
        new_events = all_events  # resend if all already sent

    to_send = new_events[:MAX_EVENTS]
    message = build_events_message(to_send)

    sent, failed = 0, 0
    for chat_id, info in subscribers.items():
        if send_message(chat_id, message):
            sent += 1
        else:
            failed += 1

    # Save sent IDs
    sent_ids.update(e["id"] for e in to_send)
    save_sent_ids(sent_ids)

    log.info(f"Broadcast done: {sent} sent, {failed} failed.")
    return {"sent": sent, "failed": failed, "events": len(to_send)}


# ─── Telegram Webhook Handler ─────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    message = data.get("message", {})
    chat    = message.get("chat", {})
    text    = message.get("text", "").strip()
    chat_id = str(chat.get("id", ""))
    name    = chat.get("first_name", "Friend")
    username = chat.get("username", "")

    if not chat_id:
        return "ok"

    subscribers = load_subscribers()

    if text == "/start":
        if chat_id not in subscribers:
            subscribers[chat_id] = {
                "name":     name,
                "username": username,
                "joined":   datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            save_subscribers(subscribers)
            log.info(f"New subscriber: {name} ({chat_id})")

        send_message(chat_id,
            f"👋 Hey *{name}*! Welcome to *Giftkarimi Tech Events Bot*! 🎉\n\n"
            f"You're now subscribed to receive *free online tech events* daily.\n\n"
            f"📅 Events are sent every day at 8:00 AM\n"
            f"🔕 Type /stop anytime to unsubscribe\n"
            f"📋 Type /events to get today's events right now!\n\n"
            f"Share this bot with friends: @Giftkarimi\\_bot"
        )

    elif text == "/stop":
        if chat_id in subscribers:
            del subscribers[chat_id]
            save_subscribers(subscribers)
        send_message(chat_id,
            "😢 You've been unsubscribed.\n\n"
            "Type /start anytime to subscribe again!"
        )

    elif text == "/events":
        all_events = get_eventbrite_events()
        to_send    = all_events[:MAX_EVENTS]
        message    = build_events_message(to_send)
        send_message(chat_id, message)

    elif text == "/count":
        count = len(subscribers)
        send_message(chat_id, f"👥 *Total subscribers:* {count}")

    elif text == "/help":
        send_message(chat_id,
            "🤖 *Giftkarimi Tech Events Bot*\n\n"
            "Available commands:\n"
            "/start — Subscribe to daily events\n"
            "/stop — Unsubscribe\n"
            "/events — Get today's events now\n"
            "/count — See total subscribers\n"
            "/help — Show this message\n\n"
            "Share with friends: @Giftkarimi\\_bot"
        )

    else:
        send_message(chat_id,
            "Type /help to see available commands 😊"
        )

    return "ok"


# ─── Admin Panel ──────────────────────────────────────────────────────────────

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
  .stat-value { font-size: 20px; font-weight: bold; color: #fff; }
  .btn { width: 100%; padding: 14px; border: none; border-radius: 10px;
         font-size: 15px; font-weight: 600; cursor: pointer; margin-bottom: 10px;
         transition: opacity 0.2s; }
  .btn:active { opacity: 0.7; }
  .btn-primary { background: linear-gradient(135deg, #7c8cf8, #5b6cf8); color: #fff; }
  .btn-danger  { background: linear-gradient(135deg, #f87c7c, #f85b5b); color: #fff; }
  .btn-success { background: linear-gradient(135deg, #7cf8a8, #5bf880); color: #111; }
  .subscriber { display: flex; align-items: center; padding: 10px 0;
                border-bottom: 1px solid #2a2a4a; }
  .subscriber:last-child { border-bottom: none; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; background: #7c8cf8;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; color: #fff; margin-right: 12px; font-size: 14px; flex-shrink: 0; }
  .sub-info { flex: 1; }
  .sub-name { font-size: 14px; font-weight: 600; }
  .sub-meta { font-size: 11px; color: #888; margin-top: 2px; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
           background: #2a2a4a; color: #fff; padding: 12px 24px; border-radius: 30px;
           font-size: 14px; display: none; z-index: 99; }
  .login-wrap { display: flex; align-items: center; justify-content: center;
                min-height: 100vh; }
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

<!-- Login -->
<div class="login-wrap" id="loginWrap">
  <div class="login-card">
    <h2>🤖 Admin Panel</h2>
    <p>Giftkarimi Tech Events Bot</p>
    <input type="password" id="pwInput" placeholder="Enter password" />
    <button class="btn btn-primary" onclick="login()">Login</button>
  </div>
</div>

<!-- Admin Panel -->
<div id="adminPanel">
  <div class="header">
    <h1>🖥️ Giftkarimi Bot</h1>
    <p>Admin Dashboard</p>
  </div>

  <div class="container">

    <!-- Stats -->
    <div class="card">
      <h2>📊 Stats</h2>
      <div class="stat">
        <span class="stat-label">Total Subscribers</span>
        <span class="stat-value" id="subCount">—</span>
      </div>
      <div class="stat">
        <span class="stat-label">Bot Username</span>
        <span class="stat-value" style="font-size:14px">@Giftkarimi_bot</span>
      </div>
      <div class="stat">
        <span class="stat-label">Daily Send Time</span>
        <span class="stat-value" style="font-size:14px">8:00 AM</span>
      </div>
    </div>

    <!-- Actions -->
    <div class="card">
      <h2>⚡ Actions</h2>
      <button class="btn btn-success" onclick="broadcast()">📤 Send Events to All Subscribers Now</button>
      <button class="btn btn-primary" onclick="loadSubscribers()">🔄 Refresh Subscribers</button>
      <div class="result-box" id="resultBox"></div>
    </div>

    <!-- Subscribers -->
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
  fetch("/admin/stats", {
    headers: { "X-Admin-Password": password }
  }).then(r => {
    if (r.ok) {
      document.getElementById("loginWrap").style.display = "none";
      document.getElementById("adminPanel").style.display = "block";
      loadData();
    } else {
      showToast("❌ Wrong password");
    }
  });
}

function loadData() {
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } })
    .then(r => r.json())
    .then(d => {
      document.getElementById("subCount").textContent = d.subscriber_count;
    });
  loadSubscribers();
}

function loadSubscribers() {
  fetch("/admin/subscribers", { headers: { "X-Admin-Password": password } })
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById("subList");
      if (!data.subscribers || data.subscribers.length === 0) {
        list.innerHTML = '<p style="color:#888;font-size:13px">No subscribers yet. Share @Giftkarimi_bot!</p>';
        return;
      }
      list.innerHTML = data.subscribers.map(s => `
        <div class="subscriber">
          <div class="avatar">${s.name[0].toUpperCase()}</div>
          <div class="sub-info">
            <div class="sub-name">${s.name}</div>
            <div class="sub-meta">${s.username ? "@" + s.username : "No username"} · Joined ${s.joined}</div>
          </div>
        </div>
      `).join("");
      document.getElementById("subCount").textContent = data.subscribers.length;
    });
}

function broadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Sending events...";
  fetch("/admin/broadcast", {
    method: "POST",
    headers: { "X-Admin-Password": password }
  }).then(r => r.json()).then(d => {
    box.textContent = `✅ Done! Sent to ${d.sent} subscribers. ${d.events} events included.`;
    showToast("✅ Events sent!");
  }).catch(() => {
    box.textContent = "❌ Something went wrong.";
  });
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.display = "block";
  setTimeout(() => t.style.display = "none", 3000);
}

document.getElementById("pwInput").addEventListener("keydown", e => {
  if (e.key === "Enter") login();
});
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
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    subs = load_subscribers()
    return jsonify({
        "subscriber_count": len(subs),
        "send_time":        SEND_TIME,
    })

@app.route("/admin/subscribers")
def admin_subscribers():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    subs = load_subscribers()
    return jsonify({
        "subscribers": [
            {"name": v["name"], "username": v.get("username",""), "joined": v["joined"]}
            for v in subs.values()
        ]
    })

@app.route("/admin/broadcast", methods=["POST"])
def admin_broadcast():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    result = broadcast_events()
    return jsonify(result)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": "Giftkarimi_bot"})


# ─── Scheduler Thread ─────────────────────────────────────────────────────────

def run_scheduler():
    schedule.every().day.at(SEND_TIME).do(broadcast_events)
    log.info(f"Scheduler running — daily broadcast at {SEND_TIME}")
    while True:
        schedule.run_pending()
        time.sleep(30)


# ─── Setup Webhook ────────────────────────────────────────────────────────────

def setup_webhook():
    railway_url = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if railway_url:
        webhook_url = f"https://{railway_url}/webhook/{TELEGRAM_BOT_TOKEN}"
        set_webhook(webhook_url)
    else:
        log.warning("No RAILWAY_STATIC_URL found — webhook not set. Set it manually after deploy.")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_webhook()
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info(f"Starting server on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
