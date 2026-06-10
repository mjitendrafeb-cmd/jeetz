#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — auto-generated and sent via Gmail SMTP.
Reads GMAIL_USER and GMAIL_APP_PASSWORD from environment (GitHub Secrets).
"""

import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

RECIPIENT = "Jitendra.Meghrajani@careedge.in"

def build_report(today: datetime.date) -> str:
    date_str = today.strftime("%B %d, %Y")
    day_str  = today.strftime("%A")

    report = f"""\
================================================================================
                     DAILY CREDIT INTELLIGENCE REPORT
================================================================================
  Jitendra Meghrajani
  Jitendra.Meghrajani@careedge.in

  Report Date : {date_str} ({day_str})
  Distribution: Personal / Proprietary
================================================================================

================================================================================
  === CRITICAL ===
  High-conviction ideas and urgent credit events requiring immediate attention
================================================================================

  1. [ISSUER / TICKER]
     Rating     : [Current Rating]  |  Outlook: [Stable / Negative / Positive]
     Spread     : [Current OAS/Z-spread vs. Benchmark]
     Key Event  : [Earnings / Covenant breach / Refinancing deadline / etc.]
     Action     : [Buy / Sell / Hold / Watch]
     Rationale  : [Brief thesis — 1-2 sentences]

  2. [ISSUER / TICKER]
     Rating     : [Current Rating]  |  Outlook: [...]
     Spread     : [...]
     Key Event  : [...]
     Action     : [...]
     Rationale  : [...]

--------------------------------------------------------------------------------

================================================================================
  === IMPORTANT ===
  Significant developments that warrant monitoring or position review
================================================================================

  1. [ISSUER / TICKER]
     Sector     : [Sector / Sub-sector]
     Development: [Rating action / Macro headwind / Sector rotation / etc.]
     Impact     : [Spread widening / tightening, duration risk, liquidity note]
     Suggested  : [Review position / Reduce exposure / Add on dips]

  2. [ISSUER / TICKER]
     Sector     : [...]
     Development: [...]
     Impact     : [...]
     Suggested  : [...]

  3. [ISSUER / TICKER]
     Sector     : [...]
     Development: [...]
     Impact     : [...]
     Suggested  : [...]

--------------------------------------------------------------------------------

================================================================================
  === WATCHLIST ===
  Names to monitor over the next 5-10 trading days
================================================================================

  - [ISSUER A]   | [Reason: upcoming maturity / earnings / rating review]
  - [ISSUER B]   | [Reason: ...]
  - [ISSUER C]   | [Reason: ...]
  - [ISSUER D]   | [Reason: ...]
  - [ISSUER E]   | [Reason: ...]

  Macro / Rates Context:
    - UST 10Y    : [Yield]  |  2Y/10Y spread: [bps]
    - IG CDX     : [Level]  |  HY CDX: [Level]
    - Fed stance : [Current guidance / upcoming FOMC note]

--------------------------------------------------------------------------------

================================================================================
  === ANALYST DEVELOPMENT ===
  Research, frameworks, and skill-building focus for the day
================================================================================

  Reading / Case Study:
    - [Paper / Report / Book chapter title]
      Source : [Author / Publication]
      Theme  : [Distressed / LBO / Covenant / Macro credit / Structured]
      Takeaway: [One sentence on key learning]

  Model / Framework Work:
    - [Task: Build / refine / review a DCF, waterfall, covenant model, etc.]
      Context: [Issuer or hypothetical scenario]
      Goal   : [Specific skill or output target]

  Concept to Deepen:
    - [Topic: e.g., PIK toggles, EBITDA add-backs, debt capacity analysis]
      Resource: [Link / textbook / Bloomberg article]

--------------------------------------------------------------------------------

================================================================================
  === TOP 10 CREDIT WATCHLIST ===
  Ranked by conviction / near-term catalyst
================================================================================

   #  | Issuer / Ticker        | Sector          | Rating | Spread | Action
  ----|------------------------|-----------------|--------|--------|----------
   1  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   2  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   3  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   4  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   5  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   6  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   7  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   8  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
   9  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]
  10  | [Issuer]               | [Sector]        | [Rtg]  | [bps]  | [Action]

================================================================================

  This report is auto-generated and delivered via GitHub Actions.
  Generated on: {date_str} at 06:00 AM IST

================================================================================
"""
    return report


def send_email(subject: str, body: str, gmail_user: str, gmail_password: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = RECIPIENT

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())
        print(f"Report sent to {RECIPIENT}")


def main() -> None:
    gmail_user     = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    today   = datetime.date.today()
    subject = f"Daily Credit Intelligence Report — {today.strftime('%B %d, %Y')}"
    body    = build_report(today)

    send_email(subject, body, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
