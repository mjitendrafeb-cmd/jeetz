# Running the 7:40 CareEdge Daily News from an office machine

## One-time setup

1. Install Python 3.11 or newer.

2. Clone the repo:
       git clone https://github.com/mjitendrafeb-cmd/jeetz.git
       cd jeetz

3. Install dependencies:
       pip install -r scripts/requirements.txt
   (anthropic, requests, feedparser, beautifulsoup4, telethon, pdfplumber)

4. Create a file `run_news.bat` (Windows) next to the repo:

       @echo off
       cd /d C:\path\to\jeetz
       git pull --quiet

       rem --- mail (ask IT for these) ---
       set SMTP_HOST=smtp.office365.com
       set SMTP_PORT=587
       set SMTP_USER=news@careedge.in
       set SMTP_PASSWORD=xxxxxxxx
       set SMTP_FROM=news@careedge.in

       rem --- do not touch the git repo ---
       set LOCAL_RUN=1

       rem --- optional ---
       set ANTHROPIC_API_KEY=
       set TELEGRAM_API_ID=
       set TELEGRAM_API_HASH=
       set TELEGRAM_SESSION=

       python scripts\send_team_news.py

## Test before going live

Send only to yourself first:

       set TEST_EMAIL=jitendra.meghrajani@careedge.in
       python scripts\send_team_news.py

TEST_EMAIL restricts the run to one recipient and does NOT mark the day
as sent, so it is safe to repeat.

## Schedule it

Windows Task Scheduler -> Create Task
  Trigger : Daily, 07:35
  Action  : Start a program -> C:\path\to\run_news.bat
  Check   : "Run whether user is logged on or not"
The machine must be powered on at that time.

## Notes / gotchas

* LOCAL_RUN=1 stops the script writing to the GitHub repo. Consequence:
  the "already seen" memory and the news pool stay on THIS machine only.
  Run it from one machine consistently, or stories may repeat.

* If the office network uses a proxy, set these too:
      set HTTPS_PROXY=http://proxy.careedge.in:8080
      set HTTP_PROXY=http://proxy.careedge.in:8080

* The script fetches ~40 news and regulator sites (Google News, RBI,
  SEBI, NSE, BSE, Moneycontrol, Livemint, ET ...). If the corporate
  firewall blocks news sites, those sources return zero and the mail
  will be thin. Check the run log for "0 items" lines.

* Telegram (telethon) is often blocked on corporate networks. If so, set
  "telegram": false in config.json — everything else still works.

* Without ANTHROPIC_API_KEY (or with no credits) the mail still sends;
  classification falls back to the mechanical rules and the "Credit lens"
  lines are omitted.
