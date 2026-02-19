# 🖥️ Giftkarimi Tech Events Bot

A Telegram bot that lets friends subscribe and receive free daily tech events.
Includes a web admin panel you can open on your phone to manage everything.

---

## How It Works

1. Friends search **@Giftkarimi_bot** on Telegram and type `/start`
2. They get subscribed instantly
3. Every day at 8:00 AM, all subscribers receive free tech events
4. You manage everything from your **web admin panel**

---

## Deploy to Railway (Free, Step by Step)

### Step 1 — Push to GitHub

1. Go to https://github.com/new and create a new **private** repository called `giftkarimi-bot`
2. On your computer, open a terminal in the project folder and run:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/giftkarimi-bot.git
git push -u origin main
```

### Step 2 — Deploy on Railway

1. Go to https://railway.app and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `giftkarimi-bot` repo
4. Click **Add Variables** and add these one by one:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `8245478915:AAG_yyJHuX7D_yorjENkwjPSoqrkQEaB4zA` |
| `ADMIN_PASSWORD` | `gift2024` (change this to something secret!) |
| `SEND_TIME` | `08:00` |
| `MAX_EVENTS` | `10` |
| `EVENTBRITE_TOKEN` | (add later — see below) |

5. Click **Deploy** — Railway will build and start your bot
6. Once deployed, go to **Settings → Networking → Generate Domain**
7. Copy the domain (e.g. `giftkarimi-bot.up.railway.app`)

### Step 3 — Set the Webhook

After deploy, open your browser and go to:
```
https://api.telegram.org/bot8245478915:AAG_yyJHuX7D_yorjENkwjPSoqrkQEaB4zA/setWebhook?url=https://YOUR-RAILWAY-DOMAIN/webhook/8245478915:AAG_yyJHuX7D_yorjENkwjPSoqrkQEaB4zA
```
Replace `YOUR-RAILWAY-DOMAIN` with your actual Railway domain.

You should see: `{"ok":true,"result":true}`

### Step 4 — Test It!

1. Open Telegram, search **@Giftkarimi_bot**
2. Type `/start` — you should get a welcome message!
3. Open your admin panel at: `https://YOUR-RAILWAY-DOMAIN`
4. Password: `gift2024`

---

## Get Eventbrite Token (Free)

1. Go to https://www.eventbrite.com and create a free account
2. Visit https://www.eventbrite.com/platform/api
3. Click **Get a Free API Key**
4. Copy your Private Token
5. Add it to Railway environment variables as `EVENTBRITE_TOKEN`

Until you add it, the bot shows sample events so everything still works.

---

## Bot Commands (for subscribers)

| Command | What it does |
|---|---|
| `/start` | Subscribe to daily events |
| `/stop` | Unsubscribe |
| `/events` | Get today's events right now |
| `/count` | See total subscribers |
| `/help` | Show all commands |

---

## Admin Panel

Open `https://YOUR-RAILWAY-DOMAIN` on your phone browser.

- See total subscribers
- See who subscribed and when
- Manually trigger event broadcast to all subscribers
- Password protected

---

## Share With Friends

Just share your bot link:
```
https://t.me/Giftkarimi_bot
```

Friends tap it, press Start, and they're subscribed! No app install needed.
