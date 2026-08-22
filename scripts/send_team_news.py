#!/usr/bin/env python3
"""
send_team_news.py — Per-person watchlist news + rule-based S1-S5 digest.

Runs WITHOUT the Anthropic API (zero credits). Driven by team.json
(managed at docs/team.html): one row per company with GH/Analyst/RH
names, emails, send flags, and S1-S5 section flags.

Each enabled person receives ONE email:
  S1 = news for the companies they are mapped to (only rows with S1 ticked)
  S2-S5 = rule-classified sector/regulation/bond/macro sections, included
          if ticked on any row where that person is enabled.
"""

import os
import re
import json
import math
import html as _html
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from fetch_news import fetch_all_news

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEAM_PATH = os.path.join(_REPO_ROOT, "team.json")
_SEEN_PATH = os.path.join(_REPO_ROOT, "data", "team_seen.json")  # separate memory from
# the daily Claude report so the two systems never suppress each other's items.

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# The 7:40 mail uses THREE sections. _classify() further down still returns
# the old five, untouched, because send_credit_report.py imports it for the
# 7:30 fallback report — which must not change. _classify_team() maps the
# five onto these three.
SECTION_TITLES = {
    "S1": "Watchlist News",
    "S2": "S2 — Sector & Regulation",
    "S3": "S3 — Macroeconomic & Markets",
}

# Section routing mirrors the 7:30 report's prompt:
#   S1 — [WATCHLIST — Company] items only
#   S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating agency actions
#   S3 — RBI, SEBI, NHB regulatory circulars/orders (+ ALL penalties)
#   S4 — Bonds, G-Sec, CP, Securitisation, FIMMDA, CCIL market items
#   S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global
_S4_RE = re.compile(
    r"\b(bond[s]?|ncd[s]?|debenture[s]?|yield[s]?|g-sec|gsec|gilt[s]?|"
    r"commercial paper|\bcp\b|securitisation|securitization|fimmda|ccil|"
    r"treasury bill[s]?|t-bill[s]?|masala bond|certificate[s]? of deposit|"
    r"repo auction|vrr|\bomo\b|state (development loan|government securities)|"
    # "Government Stock" is RBI's own term for G-Secs in its auction-result
    # releases ("Government Stock - Full Auction Results") — a real 11 Aug
    # item landed in S2 instead of S3 for lacking the more common "G-Sec"
    # phrasing.
    r"government stock|"
    r"money market|debt market|coupon rate|private placement)\b",
    re.IGNORECASE,
)
_S5_RE = re.compile(
    r"\b(gdp|inflation|cpi|wpi|iip|core sector|repo rate|monetary policy|\bmpc\b|"
    r"fiscal deficit|current account deficit|\bcad\b|forex reserves|foreign exchange reserves|"
    r"rupee|trade deficit|\bpmi\b|gst collection|us fed|federal reserve|fomc|"
    r"ecb|global growth|crude (oil )?price|industrial production|unemployment rate|"
    # Widened to close the gap with the 7:30 AI's S5 judgment — these are all
    # topics the AI routes to Macro but the old list missed.
    r"economic growth|growth (forecast|projection|estimate)|economic survey|"
    r"rate (cut|hike)|union budget|capex cycle|monsoon|el nino|"
    r"exports?|imports?|trade (war|deal|agreement)|"
    r"(trade|import|export|customs|reciprocal|retaliatory) tariffs?|"
    r"tariffs? on (imports?|exports?|goods|steel|aluminium|chips?)|"
    r"imf|world bank|\badb\b|\boecd\b|sovereign (rating|bond)|"
    r"dollar index|us treasur(y|ies)|brent|gold price|"
    r"consumer price|wholesale price|per capita income|employment (data|rate)|"
    r"credit ratio|upgrade[- ]to[- ]downgrade ratio|india inc\b|corporate india\b|"
    r"bank of (japan|england)|\bboj\b|\bpboc\b)\b",
    re.IGNORECASE,
)
# Sources that only ever carry macro content — route straight to S5 even when
# the headline dodges every keyword (mirrors the 7:30 AI, which knows an
# RBI-DBIE / MOSPI release is macro from context, not keywords).
_S5_SOURCES = ("rbi-dbie", "macro-release", "mospi", "pib")
# "cci-india" (not bare "cci") so the prefix test cannot also swallow CCIL,
# which is a bond-market source and belongs in S4.
_S3_SOURCES = ("rbi", "sebi", "nhb", "irdai", "ibbi", "nclt",
               "cci-india", "pfrda", "rbi-enforcement")
# 7:30 rule: "Any RBI Imposes Monetary Penalty / SEBI Order / NHB Penalty or
# enforcement action ALWAYS goes to S3 — never S2 — regardless of entity."
_PENALTY_RE = re.compile(
    r"\b(monetary penalty|imposes? (a )?penalt|penalis|penaliz|"
    r"enforcement action|adjudication order|show cause notice|"
    r"debarr|cease and desist|sebi order|compounding order)\w*",
    re.IGNORECASE,
)

# Geography scope: this is an Indian credit desk (7:30 prompt: "Credit Rating
# Intelligence Agent at CareEdge Ratings"). Local financial news from other
# emerging markets leaks in through generic bond/market keywords — a Nigerian
# bond story reached S4. Drop those unless the item also concerns India.
# Major economies (US/UK/EU/China/Japan) are NOT listed: the 7:30 S5 explicitly
# admits "US Fed, global" macro.
_OUT_OF_SCOPE_GEO_RE = re.compile(
    r"\b(nigeria|nigerian|kenya|kenyan|ghana|uganda|tanzania|zimbabwe|zambia|"
    r"pakistan|bangladesh|sri lanka|nepal|myanmar|"
    r"philippine|vietnam|indonesia|malaysia|thailand|"
    r"brazil|argentin|colombia|mexico|peru|chile|"
    r"turkey|turkish|egypt|morocco|south africa|naira|shilling|"
    r"cedi|ringgit|baht|peso|rand)\w*"
    r"|\b(fmdq|nasd\s+otc|ngx\s+(exchange|group))\b"
    r"|\bN\d[\d,.]*\s?(bn|billion|trn|trillion)\b",
    re.IGNORECASE,
)
_INDIA_RE = re.compile(
    r"\b(india|indian|bharat|rbi|sebi|irdai|nhb|nabard|sidbi|nse|bse|"
    r"rupee|crore|lakh|nbfc|hfc|mumbai|delhi|bengaluru|chennai|kolkata|"
    r"g-sec|gst|mpc|repo rate|dalal street|nifty|sensex)\w*",
    re.IGNORECASE,
)
# Country-code TLDs of sources that publish other markets' local news
# (e.g. streamlinefeed.co.ke). Not a blocklist of the outlet — a scope signal.
_FOREIGN_TLD_RE = re.compile(
    r"\.(ke|ng|gh|ug|tz|zw|pk|bd|lk|np|ph|vn|id|my|th|br|ar|mx|tr|eg|za)\b",
    re.IGNORECASE,
)


def _is_out_of_scope(it: dict) -> bool:
    """True when the story is another market's local news with no India angle."""
    body = f'{it["title"]} {it["summary"]}'
    if _INDIA_RE.search(body) or _INDIA_RE.search(it["source"]):
        return False
    return bool(_OUT_OF_SCOPE_GEO_RE.search(body)
                or _FOREIGN_TLD_RE.search(it["source"]))

# Throughout this file, a "these two phrases in the same clause" gap
# pattern (originally a bare negated-period character class) is used to
# stop a match at a sentence boundary. That plain form excludes EVERY
# literal period -- including the decimal point in a rupee amount. "Ugro
# Capital allots Rs 48.9 crore commercial paper" has "allots" and
# "commercial paper" only 15 characters apart, well inside any {0,N}
# budget below, but the decimal point in "48.9" was an impassable wall:
# the gap could not be crossed, so the match failed and the story fell
# through to the generic S3 default instead of being recognised as the
# entity's own CP issuance. Decimal rupee/percentage figures are
# extremely common in Indian financial headlines, so this silently broke
# an unknown number of entity-story, rating-action, management-change and
# junk-pattern matches wherever a number happened to sit between the two
# halves. Every occurrence below now also accepts a digit-dot-digit
# sequence through the gap, so a decimal point no longer blocks it while
# a real sentence-ending period still does.

# Mechanical version of the 7:30 report's AI SKIP rules (stock tips, target
# price calls, awards, CSR, consumer product launches). Same intent, no AI.
_TEAM_JUNK_RE = re.compile(
    r"\b(buy|sell|hold|accumulate|reduce|add|neutral|not rated)\b(?:\d\.\d|[^.|]){0,70}\btarget\b"
    r"|\bfor the target\b"
    r"|\btarget (price|rs\.?)\b"
    # "<Company> Share Price Target at Rs 1,220: Anand Rathi" -- reversed
    # word order ("Price Target" not "Target Price") with the brokerage
    # named only at the very end, so it slipped past every pattern above.
    # Reported directly: this exact headline shape reached S1 tagged to
    # "Anand Rathi Share and Stock Brokers Limited" (the brokerage
    # ISSUING the call, not its subject) purely because its own name is a
    # watchlist entity and appeared in the text -- the target-price call
    # was about Max Healthcare, unrelated to Anand Rathi itself. This is
    # already meant to be dropped regardless of which company issues or
    # is issued it, per the 7:30 SKIP rule this file already mirrors
    # ("stock tips, target price calls") -- this just closes the one word
    # order that rule hadn't covered.
    r"|\bshare price target\b"
    # Abbreviated broker calls: "The Ramco Cements Hold TP 1050", "HDFC Bank
    # Buy TP 2100". The spelled-out "target price" was caught but the TP/TGT
    # shorthand was not — harmless for a cement issuer (no FI signal, so it
    # was dropped anyway) but any FINANCIAL issuer sailed into S2. A digit
    # must follow, so "Motor TP directions" (third-party motor insurance)
    # is not mistaken for a price target.
    r"|\b(tp|tgt)\b\s*:?\s*(rs\.?\s*)?\d"
    r"|\b(buy|sell|hold|accumulate|reduce|add|neutral|outperform|underperform|"
    r"overweight|underweight)\b(?:\d\.\d|[^.|]){0,25}\b(tp|tgt)\b\s*:?\s*(rs\.?\s*)?\d"
    r"|\b(rated|maintains?|reiterates?|recommends?|upgrades? to|downgrades? to) ['‘“\"]?(strong )?(buy|sell|hold|accumulate|reduce|neutral|overweight|underweight)\b"
    r"|\bbuy,? sell or hold\b"
    r"|\bstock (pick|tip|recommendation)s?\b"
    r"|\bbrokerage[s]? (say|view|pick)"
    r"|\b(wins?|receives?|bags?|conferred) .{0,40}award\b|\bfelicitat"
    r"|\bcsr (initiative|activity|spend)"
    r"|\blaunch(es|ed)? .{0,30}\b(app|campaign|scheme|platform|card|savings account)\b"
    # Technical-analysis / chart noise (MarketsMojo, TradingView and similar).
    # Never credit-relevant, and it dominates Google's top slots for small caps.
    r"|\b(golden|death) cross\b"
    r"|\btechnical(s\b|\s+(signal|momentum|improvement|indicator|analysis|chart|outlook|strength|weakness))"
    r"|\b(moving average|rsi|macd|bollinger|candlestick|support and resistance)\b"
    # Stock-recommendation grade changes (NOT credit rating grades — those use
    # AAA/AA/BBB etc, which deliberately do not appear in this word list).
    r"|\b(upgraded|downgraded|upgrade[sd]?|downgrade[sd]?) to (strong )?(buy|sell|hold|accumulate|reduce|neutral|outperform|underperform)\b"
    r"|\brevenue breakdown\b"
    r"|\b52[- ]week (high|low)s?\b"
    # "Aurobindo Pharma among 8 stocks hitting 52-week highs", "Reliance,
    # ITC among 10 stocks that saw highest buying by LIC" — stock-list
    # listicles. The plural "highs" also slipped past the 52-week pattern
    # above, which required a word boundary right after "high".
    r"|\bamong \d+ stocks?\b|\bamong the \d+ stocks?\b"
    r"|\b\d+ stocks? (that|which|to)\b|\bsee full list\b"
    r"|\bhitting (52[- ]week|record|all[- ]time|lifetime) (high|low)s?\b"
    r"|\bsubscribe\b.{0,60}\bipo\b|\bipo\b.{0,60}\bsubscribe\b"
    r"|\b(gmp|grey market premium)\b"
    # Mutual-fund scheme/NAV pages — matched S4 on 'gilt' but carry no news
    # ("Kotak Gilt Investment Regular-IDCW Quarterly - NAV, Reviews...").
    r"|\bnav\b.{0,40}\b(review|asset allocation|scheme|portfolio)\b"
    r"|\b(idcw|direct plan|regular plan)\b"
    # Scheme-page variants ("Kotak Bond - Short Term Fund - Regular (G)")
    # and exchange listing notices for fund units/ETFs.
    r"|\b(regular|direct)\s*\(\s*(g|idcw|growth)\s*\)"
    r"|\blisting of (units|equity shares|securities)\b"
    # IPO debut / listing-pop stories and the investor-advice questions
    # that ride on them ("makes a strong debut with 22% premium. Should
    # investors book profits or stay invested?").
    r"|\bdebut with .{0,20}premium\b"
    r"|\blists? at .{0,15}premium\b"
    r"|\bshould investors? (book|buy|sell|stay|exit|subscribe)\b"
    r"|\bbook profits\b|\bstay invested\b"
    r"|\basset allocation\b.{0,30}\breview"
    r"|\bfund (performance|returns?) (review|analysis)\b"
    # Broker research notes titled "<Company> | <Broker> View" slip past the
    # "target price" pattern above when the price/rating isn't in the title.
    r"|\b(motilal oswal|anand rathi|icici securities|hdfc securities|kotak securities|"
    r"nuvama|jm financial|prabhudas lilladher|sharekhan|axis securities|emkay|"
    r"nirmal bang|geojit|angel one|5paisa|iifl|yes securities|edelweiss|"
    r"choice broking|ventura securities|jefferies|morgan stanley|goldman sachs|"
    r"citi\b|jp morgan|bernstein|cirtl)\b.{0,20}\bview\b"
    # Broker-house forecasts and calls are research opinion, not sector news
    # ("Motilal Oswal sees private banks delivering 18-20% earnings growth").
    # Regulator/economist forecasts (RBI, IMF, economic survey) stay — the
    # list here is brokerages and sell-side desks only.
    r"|\b(motilal oswal|anand rathi|icici securities|hdfc securities|kotak securities|"
    r"nuvama|jm financial|prabhudas lilladher|sharekhan|axis securities|emkay|"
    r"nirmal bang|geojit|angel one|5paisa|iifl securities|yes securities|"
    r"jefferies|morgan stanley|goldman sachs|citi\b|jp morgan|bernstein|clsa|"
    r"macquarie|\bubs\b|\bhsbc\b|bofa|nomura)\b"
    r"(?:\d\.\d|[^.|]){0,60}\b(sees?|expects?|estimates?|forecasts?|projects?|pegs?|says?)\b"
    # "Can X's buyback boost its share price? Here's what <broker> says"
    r"|\bhere'?s what\b(?:\d\.\d|[^.|]){0,40}\b(says?|think|expects?)\b",
    re.IGNORECASE,
)

# Tribunal cause-list / case-number entries ("Appeal No. 6967 of 2026 filed
# by Jatin...") are procedural listings, not news. When they concern a
# watchlist entity the entity's own tagged feed carries the story — the bare
# listing is dropped for everyone else.
_TRIBUNAL_LISTING_RE = re.compile(
    r"\b(appeal|petition|application|company appeal|interlocutory application|"
    r"misc(ellaneous)? application|company petition|writ petition)"
    r"\s*(\(\w+\)\s*)?no\.?\s*\d+\s*(of|/)\s*\d{2,4}\b"
    r"|\border in the matter of\b"
    r"|\bcause list\b"
    # SEBI/recovery-officer procedural notices ("Release order for Recovery
    # Certificate No. 1969 of 2019...", "Notice(s) of Attachment dated...").
    r"|\brecovery certificate\b"
    r"|\bnotices? of attachment\b"
    r"|\brc no\.?\s*\d+\b"
    r"|\brelease order for\b"
    r"|\battachment (order|notice)\b"
    # SEBI settlement/adjudication orders naming an individual or one
    # company ("Settlement Order in respect of Mr. X in the matter of Y").
    r"|\bsettlement order\b"
    r"|\b(adjudication order|order) in respect of\b"
    # "General Remittance Order dated August 05, 2026 issued under RC No,"
    r"|\bremittance order\b"
    r"|\bissued under rc no\b",
    re.IGNORECASE,
)

# Sources that never carry credit-relevant news for this desk, whatever the
# headline says: dedicated stock-tip feeds, HR/headcount data scrapers
# (reveliolabs "Auxilo Finserve Number of Employees 2026"), and crypto sites.
_JUNK_SOURCE_RE = re.compile(
    r"(@brokerage_report|reveliolabs|bitcoinworld|coindesk|cointelegraph|"
    r"zippia|growjo|leadiq|craft\.co|owler|rocketreach|"
    # Minnesota-based African-diaspora community newspaper -- zero credit
    # relevance, reported source of Bali/travel content reaching S2/S3.
    r"\bmshale\b|"
    # Upstox's own blog/market-commentary content -- broker-published stock
    # tips and market recaps, same class of noise as @brokerage_report.
    # Matches the SOURCE field (Upstox as publisher), not mentions of
    # Upstox in other outlets' articles.
    r"\bupstox\b|"
    # Wrestling/pro-wrestling news site -- zero credit relevance, reported
    # source of noise reaching S2/S3.
    r"fightful\.com)",
    re.IGNORECASE,
)
# Crypto trading stories reach S1 through loose company-name matches (an
# "…Supplies 40,000 ETH To Spark" item was tagged to Spark Institutional
# Equities). Bare "crypto"/"blockchain" are deliberately NOT here — RBI/SEBI
# crypto regulation is legitimate S3 news.
_CRYPTO_RE = re.compile(
    r"\b(bitcoin|ethereum|usdt|usdc|\bbtc\b|\beth\b|bitfinex|binance|"
    r"altcoin|stablecoin|memecoin|defi protocol|crypto (exchange|wallet|token))\b",
    re.IGNORECASE,
)
# Directory/dataset pages that are not news at all.
_NOT_NEWS_RE = re.compile(
    r"\bnumber of employees\b|\b(company|employee|headcount) (profile|data|statistics)\b|"
    r"\b(revenue|funding) (and|&) (employees|headcount)\b"
    # Recurring Telegram filler and explainer content -- never a credit event.
    r"|\bipo corner\b"
    r"|^what (is|are)\b.{0,60}\?"
    r"|\bwhy .{0,40}\b(matter|matters) to investors\b"
    r"|\b(summary|round[- ]?up|recap) of (financial |the )?markets?\b"
    # Derivatives / F&O positioning tables. Market-structure noise, never a
    # credit event ("Kalyan Jewellers among 5 F&O stocks with a sharp rise
    # in futures open interest").
    r"|\bf&o\b|\bopen interest\b|\bfutures? (and options|open interest)\b"
    r"|\bderivatives? (data|strategy|outlook)\b|\block[- ]?in period\b"
    # Daily market wraps and gainer/loser tables.
    r"|\bmarket wrap\b|\btop (gainers|losers)\b|\bgainers and losers\b"
    r"|\bnifty\b.{0,30}\bsensex\b|\bsensex\b.{0,30}\bnifty\b"
    # Deposit-rate comparison listicles ("NBFC FD rates 2026: ... offer up
    # to 8.50%; check top rates").
    r"|\bfd rates?\b|\bfixed deposit rates?\b|\bcheck (the )?top rates\b"
    # RBI Retail Direct scheme boilerplate scraped as text ("Each bank or
    # Primary Dealer (PD) ... will submit a single consolidated
    # non-competitive bid"). Instructions, not news.
    r"|\bconsolidated non-competitive bid\b|\bretail direct portal\b"
    # Foreign-exchange valuation metric pages ("Price to sales forward of
    # NuEnergy Holdings Bhd – MYX:NHB"). The MYX:NHB ticker also collided
    # with \bnhb\b (National Housing Bank) in the FI-signal regex, which is
    # how a Malaysian penny stock reached S3.
    r"|\bprice to (sales|earnings|book|cash ?flow)( forward| ratio)?\b"
    r"|\b(myx|lse|asx|sgx|nyse|nasdaq|hkex|klse|tsx|jse):\s?\S"
    r"|\binterest rates? comparison\b|\boffers? up to \d+(\.\d+)?%"
    # IPO pipeline/approval filler — not a credit event for this desk.
    r"|\b(receives?|receive|gets?|get) (sebi|regulatory) (approval|nod)(?:\d\.\d|[^.|]){0,30}\bipo"
    r"|\bsebi (approval|nod)(?:\d\.\d|[^.|]){0,25}\b(launch|float)(?:\d\.\d|[^.|]){0,15}\bipos?\b"
    r"|\bipo[- ]bound\b|\bfiles? (draft )?(drhp|rhp)\b"
    r"|\bfiles? for (an? )?(draft )?ipo\b"
    # Personality profiles / fund-manager interviews.
    r"|\bis known for\b|\bin conversation with\b|\bexclusive interview\b"
    r"|\b(fund manager|cio|portfolio manager)(?:\d\.\d|[^.|]){0,25}\b(says|shares|picks|interview)\b"
    r"|\bhere'?s (what|how|why) you (need to know|should know)\b"
    # Bank holiday calendars. Branch-opening hours are not a credit event,
    # but they mention banks constantly so they sailed into S2. Written to
    # require holiday context, so a genuine closure ("RBI cancels the
    # licence of X Co-operative Bank") is untouched.
    r"|\bbank holidays?\b"
    r"|\bholiday (list|calendar|schedule)\b"
    r"|\bbanks? (are |will be |to |to remain |remain )?closed\b(?:\d\.\d|[^.|]){0,60}"
    r"\b(holiday|festival|jayanti|puja|eid|diwali|independence day|republic day|"
    r"second saturday|sunday)\b"
    # RBI daily money-market operations table scraped as text ("1. Fixed
    # Rate 2. Variable Rate& (a) Repo Operation (b) Reverse Repo Operation
    # 3. MSF# ..."): a data table, not a story.
    r"|\b1\.\s*fixed rate\b.{0,30}\bvariable rate\b"
    r"|\b\(a\)\s*repo operation\b"
    r"|\b(repo|reverse repo) operation\b.{0,60}\bmsf\b",
    re.IGNORECASE,
)


# Same rule as fetch_news._STOCK_MOVE_RE, kept here because the team mailer
# also sees items that did not come through that path.
_TEAM_STOCK_MOVE_RE = re.compile(
    r"\b(shares?|stock|share price|scrip|m-?cap)\b(?:\d\.\d|[^.|]){0,40}?\b"
    r"(jump|rall(y|ies|ied)|surg|soar|zoom|spike|climb|gain|rise|rises|risen|"
    r"advanc|drop|fall|fell|slip|slid|declin|tank|plunge|crash|slump|tumbl|"
    r"sink|sank|dip)\w*"
    r"|\b(jump|rall(y|ies)|surg|soar|zoom|spike|climb|gain|drop|fall|slip|"
    r"declin|tank|plunge|crash|slump|tumbl)\w*\b(?:\d\.\d|[^.|]){0,25}\b(shares?|stock|share price)\b"
    r"|\bsell[- ]?off\b"
    r"|\bshares?\s+(up|down)\s+\d",
    re.IGNORECASE,
)


_SUPPRESS_PATH = os.path.join(_REPO_ROOT, "suppress.json")


def _load_suppressions() -> list[str]:
    """(J) Reader feedback loop. Lowercased substrings; any item whose title
    contains one is dropped. Populated from the 'not relevant' links in the
    mail, so recurring noise is killed by the reader instead of waiting for
    someone to hand-write another regex."""
    try:
        with open(_SUPPRESS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [str(x).strip().lower() for x in data.get("patterns", []) if str(x).strip()]
    except Exception:
        return []


_SUPPRESSIONS = _load_suppressions()


def _is_team_junk(it: dict) -> bool:
    t = (it.get("title") or "").lower()
    if any(pat in t for pat in _SUPPRESSIONS):
        return True
    # A Google News SEARCH page is a query, not an article — one slipped
    # into S2 as "Licensing Urban Cooperative Banks" with a /search?q= link.
    if "news.google.com/search" in (it.get("url") or ""):
        return True
    if _JUNK_SOURCE_RE.search(it["source"]):
        return True
    if _TEAM_STOCK_MOVE_RE.search(it["title"]):
        return True
    body = f'{it["title"]} {it["summary"]}'
    if _CRYPTO_RE.search(body) or _NOT_NEWS_RE.search(body):
        return True
    if (_TRIBUNAL_LISTING_RE.search(body)
            and "WATCHLIST" not in (it.get("tags") or "")):
        return True
    # Sport/entertainment/travel/lifestyle and financial data-quote pages are
    # never this desk's business. Checked here — BEFORE classification, not
    # inside it — so a trusted-source shortcut (RBI/SEBI feeds routing
    # straight to S2/S3) or a lenient AI judgement call can never let one
    # through: the item never reaches either path.
    if _NEVER_RELEVANT_RE.search(body) or _DATA_PAGE_RE.search(body):
        return True
    if _EDUCATIONAL_FILLER_RE.search(it.get("title", "")):
        return True
    # A malformed/fragment headline is never presentable, whatever section
    # it would otherwise land in. Only checked for non-watchlist items — a
    # watchlist company's own tagged story should never be dropped for a
    # scraped-summary quirk the reader never sees in the title.
    if not it.get("wl_company") and _is_malformed_headline(it.get("title", "")):
        return True
    return bool(_TEAM_JUNK_RE.search(body))


# 7:30 rule, mechanical version: "INCLUDE only items affecting Rating
# outlook / Liquidity / Funding / Asset quality / Capitalisation /
# Governance" and "SKIP: ... Generic business news". Section regexes (S1
# tag, S3 penalty/source, S4 bonds, S5 macro) are all positive matches on
# financial content already; the one gap was the S2 catch-all -- anything
# that matched NOTHING fell into S2 by default with no relevance check at
# all, so general news (geopolitics, sports, human-interest, brokerage
# "View" notes that dodge the junk regex) leaked through. This gate requires
# an actual financial-sector signal before anything lands in the S2 default.
# Rating-agency press pages are scraped per-company ([RATING — ICRA] etc).
# For a company on somebody's watchlist that's an S1 credit event; for any
# other company it is noise about an unrelated issuer ("BEL-Thales Systems
# Ltd", "Hira Electro Smelters Limited"), and it slipped past the relevance
# gate purely because the agency's own name is a financial keyword.
_CRA_TAG_RE = re.compile(r"\bRATING\s*[—–-]", re.IGNORECASE)


def _is_cra_announcement(it: dict) -> bool:
    return bool(_CRA_TAG_RE.search(it.get("tags", "")))


# A regulator's DECISION is S3 whoever reports it. The source-based S3 rule
# only fires when the item came from the regulator's own feed, so the same
# decision written up by ET or Mint fell through to S2. Matches action verbs
# only — a story that merely cites RBI data ("RBI data shows credit growth
# at 18.6%") is sector news, not regulation. Checked AFTER the S4/S5 keyword
# tests so monetary policy still reads as macro.
_REG_ACTION_RE = re.compile(
    r"\b(rbi|sebi|irdai|nhb|pfrda|ibbi|nclt)\b(?:\d\.\d|[^.|]){0,45}?\b"
    r"(allow|permit|direct|mandat|tighten|eas(e|es|ing)|relax|issu|notif|amend|"
    r"propos|approv|bars?\b|banned|bans\b|cap(s|ped)?\b|prescrib|introduc|"
    r"extend|defer|withdraw|revis|norms?\b|guidelines?\b|circular)\w*",
    re.IGNORECASE,
)


# S2-S5 are the industry / sector / economy sections. The old gate was one
# flat OR-list that included generic money words — loan, dividend, merger,
# "raises Rs X crore", "Q1 results" — so ANY company mentioning them passed.
# That is how Bharti Airtel, Aircel and an EPL story reached the NBFC/FI
# section: they are ordinary corporate or sports stories that happen to
# contain finance vocabulary. Three tiers now, instead of one list.

# Tier 0 — never this desk's business, whatever finance words appear.
_NEVER_RELEVANT_RE = re.compile(
    r"\b(premier league|\bepl\b|football|soccer|cricket|\bipl\b|world cup|fifa|"
    r"olympic|tournament|match (report|preview|day)|wicket|goalkeeper|transfer window|"
    r"live score|fixture|kick-?off|\bvs\.?\b.{0,20}\b(live|score|preview)|"
    r"\b(utd|united|fc|club)\b(?:\d\.\d|[^.|]){0,15}\bvs\.?\b|"
    r"box office|bollywood|tollywood|film|movie|web series|streaming (show|series)|"
    r"celebrity|actor|actress|singer|awards? (show|night)|reality show|"
    r"\bgame night\b|"
    # Travel/tourism/hospitality/lifestyle content. Root cause of the Bali
    # leaks: these stories carry no finance vocabulary at all in most cases
    # (so _FI_SIGNAL_RE alone would already reject them), but a source/tag
    # coincidence (e.g. a mis-tagged watchlist match, or a trusted-source
    # bypass) can still let them through the section router. Blocking the
    # TOPIC directly — not the word "Bali" — closes that whichever entity
    # or source happened to carry it.
    r"travel (guide|itinerary|advisory)|\bvacation\b|"
    r"honeymoon|\b(beach|spa) resort\b|\bresort\b|homestay|\bbnb\b|airbnb|"
    r"things to do in|places to visit|travel destination|"
    r"\bcuisine\b|street food|nightlife|"
    # Religious/cultural ritual coverage (the literal word "bali" is a Hindu/
    # Balinese ritual and place-name; caught here as a TOPIC, not a keyword
    # blacklist — "Karkidaka Vavu Bali" ritual stories, temple ceremonies).
    r"\britual[s]?\b|pilgrimage|temple (ceremony|festival)|\bvavu\b|"
    r"\bhotel\b.{0,25}\b(review|booking|chain|guest)\b)\b",
    re.IGNORECASE,
)

# Financial DATA/quote pages (option chains, ticker quote pages) that are not
# news at all — "Price to sales forward of NuEnergy Holdings Bhd" was one
# instance of this broader category; a Yahoo Finance options page is another.
_DATA_PAGE_RE = re.compile(
    r"\byahoo finance\b|\boptions? chain\b|\bimplied volatility\b|"
    r"\bstrike price\b|\b(call|put) options?\b.{0,20}\bexpiry\b|"
    r"\bstock quote\b|\bshare price today\b|\blive (price|quote)\b|"
    # Aggregator quote-page titles list the same metric twice in one title
    # ("L&T Finance Share Price, L&T Finance Stock Price, L&T Finance Ltd")
    # — a real 11 Aug leak that the single-mention patterns above missed.
    r"\bshare price\b.{0,60}\bstock price\b|\bstock price\b.{0,60}\bshare price\b",
    re.IGNORECASE,
)

# Generic educational/promotional filler, often from Telegram channels —
# "explainer" content with no new development, and engagement-bait posts
# ("learn more...share more 👍"). Two real 11 Aug examples: "Dollar Index
# and Its Impact on the Indian Economy" and "We are starting a bond market
# jargon series..... learn more.... share more". A story with an actual new
# development uses concrete facts/numbers in its own headline; these do not.
_EDUCATIONAL_FILLER_RE = re.compile(
    r"^(dollar index and its|understanding|what is|explained:|explainer:)\b"
    r"|\blearn more\b.{0,20}\bshare more\b"
    r"|\bwant a\b.{0,30}\?\s*$|\bhow to invest in\b.{0,20}\?"
    r"|\bwe are starting a\b.{0,20}\bseries\b"
    r"|[\U0001F300-\U0001FAFF☀-➿]",  # emoji anywhere in the headline
    re.IGNORECASE,
)

# Headline-quality gate: reject records that are not a real headline at all
# — a mid-paragraph fragment, a scraped table/list remnant, or a truncated
# sentence with no understandable subject. Examples that reached production:
# "time to time.Investment by Non-Residents23" (RBI circular body text with
# a page-number artifact glued on), "rather than after the loss has
# crystallised" (mid-sentence fragment). These slipped through because a
# TRUSTED SOURCE (e.g. the RBI feed) routes straight to a section with no
# headline-quality check at all — the fix has to be a gate that runs before
# any source-trust shortcut, not another keyword.
_FRAGMENT_STARTERS = (
    "rather than", "which ", "that ", "and ", "but ", "however", "meanwhile",
    "time to time", "read more", "click here", "for more detail",
    "for more information", "continued from", "subject to the above",
    "in this regard", "as mentioned above", "as mentioned below",
    "the above ", "as per the ", "provided that", "notwithstanding",
    "not relevant?",
)


def _is_malformed_headline(title: str) -> bool:
    t = (title or "").strip()
    if len(t) < 8:
        return True
    if t.lower().startswith(_FRAGMENT_STARTERS):
        return True
    # A scraped run-on where a sentence break has no space before the next
    # capitalised word ("time to time.Investment by Non-Residents23").
    if re.search(r"[a-z]\.[A-Z]", t):
        return True
    # A headline beginning mid-sentence (lowercase first letter). Real
    # headlines from every feed this desk uses are properly capitalised, so
    # this is a safe general signal rather than a word-specific patch.
    if t[0].islower():
        return True
    # An unclosed leading parenthesis is a scraped date/citation fragment,
    # not a headline ("(Press Release dated January 16, 2025 (").
    if t.startswith("(") and t.count("(") != t.count(")"):
        return True
    # A bare "Org Name - domain.tld" with no verb or event — a scraped page
    # title, not a story ("Insolvency and Bankruptcy Board of India -
    # ibbi.gov.in"). Real headlines describe something happening.
    if re.match(r"^[A-Za-z0-9 .,&'-]+ - [\w.-]+\.(com|in|org|gov\.in|co\.in)$", t):
        return True
    return False

# Tier 1 — a financial-sector signal. REQUIRED for anything to land in S2.
# Deliberately excludes bare corporate-action words: an acquisition or a
# Q1 result is only S2 news when the subject is a financial institution.
_FI_SIGNAL_RE = re.compile(
    # Plural forms ("NBFCs", "HFCs", "insurers", "lenders") were previously
    # unmatched: \bnbfc\b requires a word boundary right after "nbfc", which
    # fails against "NBFCs" because the trailing "s" is part of the same
    # word. That silently broke every SECTOR-WIDE headline using the plural
    # ("Gold-loan NBFCs see asset quality stress...") while the singular
    # ("An NBFC raised...") kept working — exactly backwards for a desk that
    # mostly wants sector-wide (plural) stories in S2.
    r"\b(nbfc[s]?|hfc[s]?|housing finance|non-?banking financial|bank(s|ing)?|"
    r"microfinance|\bmfi[s]?\b|fintech|broking|brokerage|stock broker[s]?|"
    r"insurer[s]?|insuranc\w*|irdai|mutual fund[s]?|\bamc[s]?\b|asset management|"
    r"asset reconstruction|\barc[s]?\b|debenture trustee[s]?|chit fund[s]?|"
    r"small finance bank[s]?|payments? bank[s]?|cooperative bank[s]?|co-operative bank[s]?|"
    r"\brbi\b|\bsebi\b|\bnhb\b|nabard|sidbi|pfrda|\bibbi\b|"
    r"financial (services|institution[s]?)|finance (company|companies|limited|ltd)|\bfinance\b|"
    r"lender[s]?|\bnpa[s]?\b|non-performing|gross npa|net npa|"
    r"credit (rating[s]?|profile[s]?|quality|growth|cost[s]?)|capital adequacy|provisioning|"
    r"disbursement[s]?|\baum\b|assets under management|securitisation|securitization|"
    r"net interest margin[s]?|\bnim[s]?\b|gold loan[s]?|vehicle loan[s]?|personal loan[s]?|"
    r"microcredit|priority sector|"
    r"\bupi\b|\bmdr\b|digital (lending|payments?)|payment[s]? (gateway|aggregator)|"
    r"\baif[s]?\b|alternative investment fund[s]?)\b",
    re.IGNORECASE,
)

# Tier 2 — subjects from other sectors. Their stories routinely contain
# finance vocabulary ("Airtel repays loan", "Aircel lenders"), so a mere
# Tier-1 hit is not enough: they need a CORE financial-institution word.
# This keeps "Airtel Payments Bank" (genuinely an FI) while dropping
# "Airtel raises debt".
_NON_FI_SUBJECT_RE = re.compile(
    r"\b(airtel|aircel|vodafone idea|reliance jio|\bjio\b|bsnl|mtnl|"
    r"telecom|spectrum|\b[45]g\b|\barpu\b|subscriber (base|addition)|"
    r"maruti|tata motors|hyundai|two-?wheeler|passenger vehicle|\bauto sales\b|"
    r"pharma\w*|drug ?maker|vaccine|\bapi maker\b|"
    r"cement|steel (plant|mill)|mining|"
    r"airline|aviation|indigo|spicejet|"
    r"fmcg|consumer goods|beverage|apparel|retail chain|"
    r"real estate developer|realty firm)\b",
    re.IGNORECASE,
)

# The strict subset: an actual financial institution or regulator, not just
# finance vocabulary. "lender" and "loan" deliberately absent.
_FI_CORE_RE = re.compile(
    r"\b(nbfc[s]?|hfc[s]?|housing finance|non-?banking financial|bank(s|ing)?|"
    r"microfinance|\bmfi[s]?\b|fintech|broking|brokerage|insurer[s]?|insuranc\w*|irdai|"
    r"mutual fund[s]?|\bamc[s]?\b|asset management|asset reconstruction|"
    r"small finance bank[s]?|payments? bank[s]?|cooperative bank[s]?|co-operative bank[s]?|"
    r"\brbi\b|\bsebi\b|\bnhb\b|nabard|sidbi|pfrda|\bibbi\b|"
    r"financial (services|institution[s]?))\b",
    re.IGNORECASE,
)


def _is_fin_relevant(it: dict) -> bool:
    text = f'{it["tags"]} {it["source"]} {it["title"]} {it["summary"]}'
    if _NEVER_RELEVANT_RE.search(text):
        return False
    if not _FI_SIGNAL_RE.search(text):
        return False
    if _NON_FI_SUBJECT_RE.search(text) and not _FI_CORE_RE.search(text):
        return False
    return True

ROLES = (("gh_name", "gh_email", "send_gh", "gh_sections"),
         ("analyst_name", "analyst_email", "send_analyst", "analyst_sections"),
         ("rh_name", "rh_email", "send_rh", "rh_sections"))


def _load_team() -> dict:
    with open(_TEAM_PATH, encoding="utf-8") as f:
        return json.load(f)


_FILLER = {"of", "and", "the", "&", "for"}


def _phrase(name: str) -> str:
    """Contiguous prefix of the company name covering TWO significant words.
    'Bank of Baroda' -> 'bank of baroda' (a bare 'bank of' matched every
    bank headline — the BoB/BoI/BoM rows all 'matched' the same items).
    'Small Industries Development Bank' -> 'small industries'.
    'D. S. Integrated FinSec' -> 'd. s. integrated finsec' (initials are
    not significant on their own)."""
    # Normalise "&" the same way _match_companies normalises `body` -- a
    # phrase built with the literal "&" ("jammu & kashmir") never matches
    # press text that spells it "and", and vice versa.
    words = name.lower().replace(" & ", " and ").split()
    # A LEADING filler ("The Karur Vysya Bank" -> "the karur vysya") ends up
    # baked into the literal phrase, which then never matches real press
    # headlines that just drop the article ("Karur Vysya Bank..."). A
    # filler BETWEEN two significant words stays (that's what stops "Bank
    # of Baroda" from over-matching on bare "bank") -- only strip fillers
    # before the first significant word is seen.
    while words and (len(words[0].strip(".")) < 3 or words[0] in _FILLER):
        words.pop(0)
    if not words:
        return ""
    sig = 0
    for i, w in enumerate(words):
        if len(w.strip(".")) >= 3 and w not in _FILLER:
            sig += 1
        if sig == 2:
            return " ".join(words[:i + 1])
    return " ".join(words)


_SUFFIXES = {"private", "limited", "ltd", "pvt", "co", "company", "(india)", "india"}
# Words too common in BFSI headlines to identify a company on their own —
# 'small' alone must not attach an Equitas Small Finance story to SIDBI.
_COMMON = {"small", "national", "india", "indian", "bank", "finance", "financial",
           "capital", "home", "housing", "credit", "micro", "asset", "industries",
           "development", "investment", "securities", "insurance", "mutual", "fund",
           "tourism", "travel", "leisure", "hospitality"}


def _sig_words(name: str) -> list[str]:
    """First two significant words of a company name (len>=3, no fillers,
    no corporate suffixes) — used to sanity-check tag attribution."""
    out = []
    for w in name.lower().split():
        w2 = w.strip(".,()")
        if len(w2) >= 3 and w2 not in _FILLER and w2 not in _SUFFIXES:
            out.append(w2)
        if len(out) == 2:
            break
    return out


# Legal-form words only. Deliberately NOT the wider _SUFFIXES set, which
# also contains "india" — dropping that would turn SIDBI ("Small Industries
# Development Bank of India") into "sidb" and break the very case this
# function exists for.
_ACRONYM_DROP = {"private", "limited", "ltd", "ltd.", "pvt", "pvt.", "llp",
                 "plc", "inc", "inc.", "incorporated", "corporation", "corp",
                 "corp.", "company"}


def _acronym(name: str) -> str:
    """SIDBI-style initialism from the name's significant words — real
    headlines say 'SIDBI', not 'Small Industries Development Bank'.

    Legal-form words are dropped, because the FETCHER strips them before
    building its own acronym and the two must agree. They did not: for
    "Micro Units Development and Refinance Agency Limited" the fetcher
    searched "MUDRA" and correctly found a story, tagged it to the entity,
    and then this function looked for "MUDRAL" — trailing L for "Limited" —
    failed to find it, and _match_companies dropped the item as
    mis-tagged. 7:40 was discarding watchlist news it had just fetched,
    which is why a MUDRA story appeared in 7:30 but never in 7:40.
    """
    letters = [w[0] for w in name.lower().split()
               if w.strip(".,()") and w not in _FILLER
               and w.strip(".,()") not in _ACRONYM_DROP
               and not w.startswith("(")]
    a = "".join(letters)
    return a if len(a) >= 4 else ""


# Company words that are really the first half of an unrelated proper noun.
# "Navi Limited" is on the watchlist, so a Navi MUMBAI story matched on
# "navi" and landed in S1 as company news. Stripping the phrase before the
# name test is the surgical fix: a genuine "Navi Finserv raises NCDs"
# headline is untouched, because only the two-word place name disappears.
_NAME_FALSE_FRIEND_RE = re.compile(
    r"\bnavi\s+mumbai\b"
    r"|\bnew\s+delhi\b"
    r"|\bnoida\s+authority\b",
    re.IGNORECASE,
)


# Indian conglomerate prefixes. Matching one of these identifies the GROUP,
# not the company: "Bharti" is shared by Airtel, Hexacom and Enterprises;
# "Aditya Birla" by Capital, Fashion and dozens more. Requiring two matched
# words is not enough for the two-word ones, since both words ARE the
# group. When the only evidence sits inside the prefix, the story has to
# also carry a word from the REST of the entity's name.
_GROUP_PREFIX_RE = re.compile(
    r"^(aditya birla|kotak mahindra|bharti|tata|reliance|mahindra|adani|"
    r"godrej|hinduja|jindal|murugappa|piramal|shriram|bajaj|essar|vedanta|"
    r"torrent|larsen|birla|ambani|hero|apollo)\b",
    re.IGNORECASE,
)


def _mentions_company(body: str, name: str) -> bool:
    """Does the story text actually refer to this company? True when it
    contains the acronym (sidbi), any DISTINCTIVE name word (indostar,
    baroda, equitas), or at least TWO common words ('small' + 'industries').
    A single common word like 'small' is not enough — that attached
    Equitas Small Finance stories to SIDBI.

    Name words are matched on WORD BOUNDARIES. They were plain substrings,
    which is fine for a long distinctive name and disastrous for a short
    one: "REC Limited" reduces to the single word "rec", so every story
    containing "recent", "recovery" or "record" was read as REC news. Short
    watchlist names are common (REC, Navi, SMIFS), so this was mis-filing
    S1 items far beyond the case reported.
    """
    body = _NAME_FALSE_FRIEND_RE.sub(" ", body)
    if _group_prefix_only(body, name):
        return False
    acro = _acronym(name)
    if acro and re.search(r"\b" + re.escape(acro) + r"\b", body):
        # Same collision problem as a console alias (see
        # _AMBIGUOUS_ALIAS_CONTEXT): "MUDRA" is the derived acronym for
        # Micro Units Development and Refinance Agency, but it is also a
        # Hindi word and an unrelated ad agency's name. This path was
        # bypassing the alias-level guard entirely -- _match_companies'
        # tag_match sanity check calls _mentions_company directly, so a
        # bare acronym hit here made the alias context requirement moot.
        guard = _AMBIGUOUS_ALIAS_CONTEXT.get(acro.lower())
        if not guard or guard.search(body):
            return True
    words = _sig_words(name)
    matched = [w for w in words
               if re.search(r"\b" + re.escape(w) + r"\b", body)]
    if len(matched) >= 2:
        return True
    if not matched:
        return False
    # Exactly one word matched. That is enough only when the name HAS only
    # one significant word ("Navi", "REC", "Bhansali" — there is nothing
    # else to match on), or when the word is long enough to identify the
    # firm by itself.
    #
    # A short first word of a TWO-word name is usually a group prefix, not
    # an identifier: "Bharti Axa Life Insurance" matched on "bharti"
    # alone, so every Bharti Airtel, Bharti Hexacom and Bharti Enterprises
    # story became Bharti Axa news — 31 items in one edition. Same shape as
    # Tata, Aditya, Reliance, Mahindra. The 7-character floor is the rule
    # fetch_news._story_mentions_entity already uses, so both sides of the
    # pipeline now agree — disagreeing is what lost the MUDRA story.
    lone = matched[0]
    if len(words) == 1:
        return lone not in _COMMON
    return len(lone) >= 7 and lone not in _COMMON


def _group_prefix_only(body: str, name: str) -> bool:
    """True when the ONLY thing the story shares with this entity is the
    conglomerate prefix — "Aditya Birla Fashion" against "Aditya Birla Sun
    Life Mutual Fund". Requires a word from the rest of the name."""
    m = _GROUP_PREFIX_RE.match(name.strip())
    if not m:
        return False
    rest = name[m.end():]
    tail = [w.strip(".,()").lower() for w in rest.split()]
    tail = [w for w in tail
            if len(w) >= 3 and w not in _FILLER and w not in _SUFFIXES]
    if not tail:
        return False  # nothing else to distinguish it by; prefix is the name
    return not any(re.search(r"\b" + re.escape(w) + r"\b", body) for w in tail)


_URL_IN_TEXT_RE = re.compile(r"https?://\S+")
_MD_RE = re.compile(r"[*_`]{1,3}")
# A headline that is only a date ("Jul 29 2026", "29 July 2026") carries no
# information — Telegram posts often open with a date line.
_DATE_ONLY_RE = re.compile(
    r"^\W*(?:\d{1,2}[\s./-]+\w{3,9}[\s./-]+\d{2,4}"
    r"|\w{3,9}[\s./-]+\d{1,2},?[\s./-]+\d{2,4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\W*$",
    re.IGNORECASE,
)


def _tidy_text(s: str) -> str:
    """Decode HTML entities, strip inline URLs and markdown, collapse space.

    Feeds carry entities (&nbsp;, &amp;, &#39;). They have to be decoded HERE,
    at parse time, because the renderer escapes everything on the way out —
    without this a raw '&nbsp;' survives escaping and shows up literally in
    the card as '&nbsp;&nbsp;'."""
    s = _html.unescape(str(s or ""))
    s = _URL_IN_TEXT_RE.sub(" ", s)
    s = _MD_RE.sub("", s)
    return " ".join(s.split()).strip(" -–—:|·")


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _dedupe_summary(title: str, summary: str, source: str) -> str:
    """Google News RSS puts the headline in the description too
    ('<headline>&nbsp;&nbsp;<source>'), so the card printed the same
    sentence twice. Drop a summary that only repeats the title."""
    if not summary:
        return ""
    nt, ns, nsrc = _norm_key(title), _norm_key(summary), _norm_key(source)
    if not nt:
        return summary
    if ns == nt or ns in nt:
        return ""
    if ns.startswith(nt):
        extra = ns[len(nt):]
        # What's left is just the source name (or a scrap) — nothing to add.
        if extra == nsrc or len(extra) < 25:
            return ""
        return summary[len(title):].strip(" -–—:|·,")
    return summary


def _first_sentence(s: str, limit: int = 130) -> str:
    """Leading sentence/clause of a blob, capped for a headline."""
    s = s.strip()
    for sep in (". ", " | ", "? ", "! "):
        idx = s.find(sep)
        if 25 <= idx <= limit:
            return s[:idx].strip()
    return s[:limit].rstrip() + ("…" if len(s) > limit else "")


# Boilerplate that trails Telegram forwards of news articles.
_TG_TAIL_RE = re.compile(
    r"\s*(\d+\s*min read|last updated|read more|click here|share this|"
    r"subscribe|join (our )?channel|via @\S+|source\s*:.*)\s*$",
    re.IGNORECASE,
)
_TG_LEAD_DATE_RE = re.compile(
    r"^\W*(?:\d{1,2}[\s./-]+\w{3,9}[\s./-]+\d{2,4}"
    r"|\w{3,9}[\s./-]+\d{1,2},?[\s./-]+\d{2,4})\W*",
    re.IGNORECASE,
)


def _telegram_headline(body: str) -> str:
    """Pull a real headline out of a raw Telegram message.

    Channels mark the headline with *bold* markdown, and otherwise put it
    before the article URL. Without this, _parse_item's ':'/'—' splits gave
    a bare date ('Jul 29 2026') or a wall of rate-table numbers."""
    bold = re.search(r"\*\*?([^*]{20,200})\*\*?", body)
    if bold:
        head = bold.group(1)
    else:
        u = _URL_IN_TEXT_RE.search(body)
        head = body[:u.start()] if (u and u.start() > 20) else body
    head = _tidy_text(head)
    head = _TG_LEAD_DATE_RE.sub("", head)          # drop leading date line
    for _ in range(3):                              # drop trailing boilerplate
        new_head = _TG_TAIL_RE.sub("", head).strip(" -–—:|·,")
        if new_head == head:
            break
        head = new_head
    return _first_sentence(head) if head else ""


# Only a SHORT leading segment is a source label. Fetchers emit several
# shapes -- fetch_news uses "Source: Title — Summary", but the web scraper
# emits a bare headline ("[WEB — livemint.com] <headline>") and Indian
# headlines routinely end in ": Report" / ": SBI Research". Splitting on the
# first ": " unconditionally put the headline in the source slot and a
# fragment in the title ("Report (India's bank credit growth…)"), or left the
# title empty entirely ("(How RBI leeway on bulk deposit pricing…)").
_SOURCE_PREFIX_RE = re.compile(r"^([^:]{2,38}):\s+(\S.*)$", re.DOTALL)


def _split_source(body: str) -> tuple[str, str]:
    """Return (source, rest); ("", body) when the colon belongs to the headline."""
    m = _SOURCE_PREFIX_RE.match(body)
    if not m:
        return "", body
    cand, rest = m.group(1).strip(), m.group(2).strip()
    # A real source label is a short name -- not a clause.
    if len(cand.split()) > 5 or any(ch in cand for ch in "()?!;,"):
        return "", body
    return cand, rest


def _source_from_tags(tags: list[str]) -> str:
    """Fall back to the fetcher's own tag: [WEB — livemint.com] -> livemint.com."""
    for t in tags:
        m = re.match(r"(?:WEB|RATING|BSE|NSE|FINANCIALS)\s*[—–-]\s*(.+)", t.strip(), re.I)
        if m:
            return m.group(1).strip()
    for t in tags:
        if not re.match(r"^(T1|T2|WATCHLIST)\b", t.strip(), re.I):
            return t.strip()
    return ""


def _parse_item(raw: str) -> dict:
    item = re.sub(r"^\d+\.\s*", "", raw)
    tags = re.findall(r"^\[([^\]]+)\]\s*", item)
    body = re.sub(r"^(\[[^\]]+\]\s*)+", "", item)
    url = ""
    m = re.search(r"\|\s*URL:(\S+)", body)
    if m:
        url = m.group(1)
    pub = ""
    m = re.search(r"\|\s*PUB:([^|]+)", body)
    if m:
        pub = m.group(1).strip()
    tag_str = " ".join(tags)
    if "TELEGRAM" in tag_str.upper():
        # Telegram arrives as a raw 500-char message dump with no
        # "source: title — summary" structure, so the ':' / '—' splits below
        # produced garbage headlines (a bare date, or a wall of text with the
        # URL printed inline). Rebuild a clean headline + link instead.
        ch = re.search(r"TELEGRAM[^@]*(@\S+)", tag_str)
        source = ch.group(1) if ch else "Telegram"
        if not url:
            u = _URL_IN_TEXT_RE.search(body)
            if u:
                url = u.group(0).rstrip(").,;")
        title = _telegram_headline(body)
        clean = _tidy_text(body)
        rest = clean[len(title):] if clean.startswith(title) else clean
        summary = _TG_TAIL_RE.sub("", rest).strip(" -–—:|·,")[:180]
        if not title:
            title, summary = _first_sentence(clean), ""
    else:
        body = body.split(" | ")[0]
        source, rest = _split_source(body)
        title, _, summary = rest.partition(" — ")
        title, summary = _tidy_text(title), _tidy_text(summary)
        if not source:
            source = _source_from_tags(tags)
        # A date-only or stub headline is useless — promote from the summary.
        if summary and (_DATE_ONLY_RE.match(title) or len(title) < 15):
            title = _first_sentence(summary)
            summary = ""
        if len(title) > 150:
            title = _first_sentence(title, 150)
        summary = _dedupe_summary(title, summary, source)
    wl_company = ""
    for t in tags:
        # BSE / FINANCIALS carry the entity the same way WATCHLIST does —
        # they ARE exchange filings by that company. Without this they were
        # not recognised as watchlist items and could not be pinned to S1.
        # Requires an em/en dash, or a SPACED hyphen — not a bare one.
        # fetch_web emits the tag "[WATCHLIST-BSE]" with no company at all,
        # and a bare-hyphen pattern read that as WATCHLIST — "BSE",
        # inventing an entity called BSE. (That predates the BSE work: the
        # original WATCHLIST-only pattern had the same hole.)
        m2 = re.match(r"(?:WATCHLIST|BSE|FINANCIALS)\s*(?:[—–]|\s-\s)\s*(.+)",
                      t, re.IGNORECASE)
        if m2:
            wl_company = m2.group(1).strip()
    return {
        "tags": " ".join(tags),
        "wl_company": wl_company,
        "source": source.strip(),
        "title": (title or rest).strip(),
        "summary": summary.strip()[:220],
        "url": url,
        "pub": pub,
    }


def _classify(it: dict, company_phrases: list[str]) -> str | None:
    """Returns None when the story has no financial-sector relevance at all
    (general news that shouldn't appear anywhere in the digest)."""
    text = (it["tags"] + " " + it["source"] + " " + it["title"] + " " + it["summary"]).lower()
    if "watchlist" in it["tags"].lower() or any(p and p in text for p in company_phrases):
        return "S1"
    # Reached here => not a watchlist company. A CRA press-page announcement
    # about some unrelated issuer has no place in the sector sections.
    if _is_cra_announcement(it):
        return None
    # 7:30 rule: penalties/enforcement ALWAYS S3, never S2, whoever the entity.
    if _PENALTY_RE.search(text):
        return "S3"
    src = it["source"].lower()
    # Macro-only sources go to S5 before the generic "rbi*" S3 rule can grab
    # them (RBI-DBIE is macro data, not regulation).
    if src.startswith(_S5_SOURCES):
        return "S5"
    if src.startswith(_S3_SOURCES) or "sebi" in src:
        return "S3"
    if _S4_RE.search(text):
        # A regulator's circular ABOUT debentures/CP is regulation (S3), not
        # bond-market news (S4) — "SEBI tightens disclosure norms for debenture
        # trustees" is S3. Macro still wins, so an RBI growth-forecast revision
        # stays in S5 rather than being read as a regulatory action.
        if _REG_ACTION_RE.search(text) and not _S5_RE.search(text):
            return "S3"
        return "S4"
    if _S5_RE.search(text):
        return "S5"
    if _REG_ACTION_RE.search(text):
        return "S3"
    # Nothing matched a section-specific signal -- only fall into the S2
    # default if the story is actually about the financial sector. Otherwise
    # this is general news (geopolitics, sports, human-interest) that the
    # 7:30 AI's relevance judgment would never have included either.
    return "S2" if _is_fin_relevant(it) else None


# Old S3 (regulatory circulars) folds into the sector view — a rule about
# NBFC provisioning is sector news. Old S4 (bond/money markets) joins old S5
# under macroeconomic, as requested.
_TEAM_SECTION_MAP = {"S1": "S1", "S2": "S2", "S3": "S2", "S4": "S3", "S5": "S3"}
# Row-tick migration is a DIFFERENT mapping: rows were already converted to
# the new scheme, so only the legacy S4/S5 ticks still need folding.
_ROW_SECTION_MIGRATE = {"S4": "S3", "S5": "S3"}


def _kw_hit(text: str, words) -> bool:
    return any(w and w in text for w in words)


# S2 is the sector the entity operates in. Today every entity is BFSI, so a
# single shared S2 is indistinguishable from correct — but the moment a
# second sector exists, a GH covering it would otherwise receive BFSI news.
# Each entity therefore carries a sector, each sector carries its own
# keywords, and a person's S2 is the union of their entities' sectors —
# exactly the way S1 already works for companies.
_DEFAULT_SECTOR = "BFSI"


def _load_sectors(team: dict) -> dict:
    """{sector name: [keywords]}. Accepts the older flat sector_keywords
    list and folds it into the default sector, so an un-migrated team.json
    keeps working."""
    raw = team.get("sectors")
    if isinstance(raw, dict) and raw:
        out = {}
        for name, kws in raw.items():
            name = str(name).strip() or _DEFAULT_SECTOR
            out[name] = [str(w).strip().lower() for w in (kws or []) if str(w).strip()]
        return out
    legacy = team.get("sector_keywords") or []
    return {_DEFAULT_SECTOR: [str(w).strip().lower() for w in legacy if str(w).strip()]}


def _row_sector(r: dict) -> str:
    return (r.get("sector") or "").strip() or _DEFAULT_SECTOR


def _item_sectors(it: dict, sectors: dict) -> set:
    """Which sectors a story belongs to. An item the built-in rules routed to
    S2 without matching any sector keyword is generic financial-sector news,
    so it falls to the default sector rather than reaching nobody."""
    text = f'{it["tags"]} {it["source"]} {it["title"]} {it["summary"]}'.lower()
    hits = {name for name, kws in (sectors or {}).items() if _kw_hit(text, kws)}
    return hits or {_DEFAULT_SECTOR}


# A single issuer's own event — its NCD/CP allotment or redemption, its
# board meeting on a fund raise, its quarterly results — is that ENTITY's
# news, not the sector's and certainly not macro. It belongs in S1 for
# whoever tracks the entity and nowhere for everyone else. Without this,
# "Muthoot Microfin allots Rs 35 crore CP at 9.4%" reached every reader's
# S3 because "commercial paper" is a bond-market/macro keyword.
_ENTITY_STORY_RE = re.compile(
    # "approves?" added after a real 11 Aug leak: "Embassy Office Parks
    # REIT approves ₹400 Cr CP issuance" reached S3 because the existing
    # board-approval pattern below requires the literal word "board" —
    # an issuer approving its OWN issuance without that word slipped
    # through. One issuer's own CP/NCD/bond decision is entity news
    # whoever within the company approved it.
    r"\b(allots?|allotted|redeems?|redeemed|prepays?|repays?|repaid|raises?|raising|"
    r"to raise|matured|matures?|part redemption|full redemption|approves?)\b"
    r"(?:\d\.\d|[^.|]){0,60}\b(ncds?|debentures?|commercial papers?|\bcp\b|bonds?|\becb\b|"
    r"external commercial borrowings?|foreign currency borrowings?)\b"
    r"|\b(ncds?|debentures?|commercial papers?|bonds?)\b(?:\d\.\d|[^.|]){0,50}"
    r"\b(allotment|redemption|maturity|coupon|issue (price|opens?|closes?))\b"
    r"|\bboard (meets?|meeting|to (meet|consider)|approves?)\b(?:\d\.\d|[^.|]){0,60}"
    r"\b(ncds?|debentures?|commercial papers?|bonds?|fund ?rais\w*|\bqip\b|rights issue)\b"
    r"|\bcoupon (rate|of)\b"
    # One issuer's own debt housekeeping: "Grasim repays Rs 750 crore in
    # matured commercial papers", "Part Redemption (Revised) of Debentures
    # of ADANI AIRPORT HOLDINGS", "issues awareness letter for ... credit
    # facilities". Entity news, never sector or macro.
    r"|\bpart redemption\b|\bawareness letter\b"
    # Recovery/attachment procedural notices against ONE named party
    # ("Notice of Attachment of Bank Accounts and Demat Accounts with AP
    # No: ..."). _TRIBUNAL_LISTING_RE already drops these pre-classification
    # when no WATCHLIST tag is present, but a rejected tag (the entity match
    # fails re-verification) fell through to here and the bare word "bank"
    # in the notice text then qualified it as generic S2 sector news via the
    # default relevance gate — a procedural notice about one party's frozen
    # account is never sector news. Matched here too so it is S1-or-nothing
    # regardless of which stage first sees it.
    r"|\bnotices? of attachment\b|\battachment (order|notice)\b"
    r"|\brecovery certificate\b|\brc no\.?\s*\d+\b|\brelease order for\b"
    r"|\bsettlement order\b|\bremittance order\b|\bissued under rc no\b"
    # A SEBI registration number identifies ONE registered intermediary, so
    # the item is that entity's own disclosure, not sector news: S1 when the
    # entity is on a watchlist, dropped otherwise. INH/INZ/INA/INP are the
    # research-analyst, broker, adviser and portfolio-manager series.
    r"|\b(inh|inz|ina|inp)\s?\d{6,9}\b"
    r"|\bsebi registration (number|no\.?)\b"
    r"|\bmatured (commercial papers?|debentures?|ncds?|bonds?)\b"
    r"|\bredemption(?:\d\.\d|[^.|]){0,25}\bdebentures?\b"
    r"|\bq[1-4]\s*(fy\s?\d+\s*)?results?\b"
    r"|\bnet profit (surges?|jumps?|rises?|falls?|declines?|drops?|up|down|grows?)\b"
    # One company's corporate actions — M&A, partnerships, buybacks — are
    # equally entity-level ("Veritas to acquire Trinity Consultants",
    # "IIFL Capital partners with Flytxt", "Tips Music's share buyback").
    r"|\b(acquires?|to acquire|acquisition of|scoops? up|takes? over|merges? with|"
    r"buys? (a )?(majority |minority |controlling )?stake)\b"
    r"|\b(partners? with|ties? up with|tie-?up with|joins? hands with|"
    r"collaborates? with|signs? (an? )?(mou|pact|agreement) with)\b"
    r"|\bshare buy-?back\b|\bbuy-?back of (shares|equity)\b"
    # A promoter's own share pledge is entity-level disclosure, not sector
    # or macro news, whichever instrument it secures ("promoter pledges 2
    # lakh shares for NCD cover", "creates pledge over shares as security").
    r"|\bpromoters?\b(?:\d\.\d|[^.|]){0,40}\bpledg\w*\b|\bpledg\w*\b(?:\d\.\d|[^.|]){0,25}\bshares?\b"
    r"|\b(revokes?|releases?) (the )?pledge\b"
    # Board/management appointments at one company. The role list is
    # corporate officers only, so "RBI appoints deputy governor" (regulator
    # news) is untouched.
    r"|\bappoints?\b(?:\d\.\d|[^.|]){0,50}\bas (an? )?(independent |non-executive |executive )?"
    r"(director|chairman|chairperson|ceo|cfo|coo|cio|md\b|managing director|president)"
    # One creditor's insolvency claim against one company.
    r"|\bnclt (admits?|approves?|rejects?|dismisses?)\b"
    # One lender's loan/project-finance deal with one borrower.
    r"|\b(extends?|sanctions?|disburses?)\b(?:\d\.\d|[^.|]){0,50}"
    r"\b(project finance|term loan|credit (line|facility))\b"
    # One company's regulatory classification ("Tata Sons remains an
    # 'upper-layer NBFC'"); the plural guard keeps list-wide stories.
    r"|\bupper[- ]layer nbfc\b",
    re.IGNORECASE,
)
# ...unless the story is about the sector as a whole ("NBFCs' NCD issuance
# hits record", "banks' Q1 results preview") — plural/collective subjects
# keep their S2/S3 routing.
_PROCEDURAL_REDEMPTION_RE = re.compile(
    r"\b(part|full) redemption\b|\bredemption of (debentures?|ncds?|bonds?)\b|"
    r"\bdebenture redemption\b|"
    # Reported: "Listing of Secured Redeemable Non-Convertible Debentures
    # of <Issuer>" and "Suspension of Trading in Debentures of the
    # Companies" both reached S3 General for non-watchlist issuers --
    # same class of pure BSE/NSE administrative housekeeping as a
    # redemption notice (a listing/trading-status intimation, not
    # analytical news), just different wording the original pattern
    # didn't cover.
    r"\blisting of\b.{0,40}\bdebentures?\b|"
    r"\bsuspension of trading\b.{0,20}\bdebentures?\b",
    re.IGNORECASE,
)
_SECTOR_WIDE_RE = re.compile(
    r"\b(banks|nbfcs|hfcs|mfis|lenders|insurers|brokerages|mutual funds|"
    r"microfinance (institutions|sector)|sector|industry|india inc|issuers|"
    r"companies|corporates)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# S2 / S3 taxonomy — analyst-facing category labels
# ---------------------------------------------------------------------------
# Ordered tuples of (code, label, regex); first match wins. Used to group and
# label S2/S3 cards so a reader scanning the section sees WHAT KIND of
# development each story is, not just a flat list. A story that matches no
# category still renders (grouped as "General") rather than being dropped —
# this is a display taxonomy, not an additional relevance filter.
_S2_TAXONOMY = (
    ("REG", "Regulatory & Policy", re.compile(
        r"\b(rbi|sebi|irdai|pfrda|ifsca|ministry of finance|\bdfs\b|\bmca\b|"
        r"department of financial services|supreme court|high court|"
        r"tribunal (rules|upholds|quashes))\b", re.IGNORECASE)),
    ("MFI", "Microfinance &amp; Retail Credit", re.compile(
        r"\b(microfinance|\bmfi[s]?\b|unsecured (credit|loan)|gold loan|"
        r"consumer finance|msme lending|vehicle finance|two-?wheeler loan|"
        r"personal loan)\b", re.IGNORECASE)),
    ("INS", "Insurance", re.compile(
        r"\b(insur\w*|irdai|premium (growth|trend|income)|claims? ratio|"
        r"solvency|bancassurance)\b", re.IGNORECASE)),
    ("CAP", "Capital Markets, AMC & AIF", re.compile(
        r"\b(mutual fund|\bamc\b|\baif\b|alternative investment fund|broking|"
        r"brokerage|stock exchange|\bnse\b|\bbse\b|securities market|demat)\b",
        re.IGNORECASE)),
    ("FIN", "Fintech & Payments", re.compile(
        r"\b(fintech|\bupi\b|\bmdr\b|digital lending|digital payments?|"
        r"payment[s]? (gateway|aggregator|bank))\b", re.IGNORECASE)),
    ("BNK", "Banks & NBFCs", re.compile(
        r"\b(nbfc|hfc|bank(s|ing)?|credit growth|\baum\b|net interest margin|"
        r"\bnim\b|asset quality|capital adequacy|liquidity|funding cost|"
        r"provisioning|\bnpa\b)\b", re.IGNORECASE)),
)
_S3_TAXONOMY = (
    ("RATES", "Rates & Liquidity", re.compile(
        r"\b(repo rate|monetary policy|\bmpc\b|banking system liquidity|"
        r"\bvrr\b|\bvrrr\b|policy transmission|money market)\b", re.IGNORECASE)),
    ("CREDIT", "Fixed Income & Credit Markets", re.compile(
        r"\b(g-sec|gilt|corporate bond spread|bond issuance|foreign (portfolio )?"
        r"(flows?|investors?) (into|in) debt|debt market)\b", re.IGNORECASE)),
    ("FX", "FX & Commodities", re.compile(
        r"\b(rupee|\binr\b|\bdxy\b|dollar index|crude|brent|gold price|"
        r"commodit\w*)\b", re.IGNORECASE)),
    ("GLOBAL", "Global Macro", re.compile(
        r"\b(\bfed\b|federal reserve|\becb\b|\bboe\b|bank of england|fomc|"
        r"us (cpi|jobs|gdp|growth)|china growth|geopolit\w*|global (rates|growth))\b",
        re.IGNORECASE)),
    ("MACRO", "India Macro", re.compile(
        r"\b(gdp|gva|\bcpi\b|\bwpi\b|\biip\b|\bpmi\b|fiscal deficit|"
        r"government borrowing|\bgst\b|tax collections?|trade deficit|"
        r"current account|employment data|rural economy|monsoon|agriculture|"
        r"capex cycle|consumption|investment indicators?)\b", re.IGNORECASE)),
)


def _categorize(it: dict, table: tuple) -> str:
    text = f'{it.get("title","")} {it.get("summary","")}'
    for code, label, rx in table:
        if rx.search(text):
            return label
    return "General"


def _classify_team(it: dict, company_phrases: list[str],
                   sectors=None, macro_kw=()) -> str | None:
    """Three-section routing for the 7:40 mail.

    Runs the existing five-section classifier first so every drop rule
    (junk, geography, relevance, CRA announcements) still applies exactly as
    tested, then maps the result. Console-supplied keywords override the
    mapping for anything that is not a watchlist hit, so the desk can steer
    borderline topics without a code change.
    """
    base = _classify(it, company_phrases)
    if base == "S1":
        # _classify calls anything carrying a WATCHLIST tag S1. But
        # _match_companies re-verifies that tag and rejects it when the
        # story does not actually mention the entity (a Navi MUMBAI story
        # tagged to "Navi Limited"). A rejected tag left the item labelled
        # S1 with no company attached: invisible in the mail, since S1
        # renders per entity, but it still inflated the S1 counts. Judge
        # such an item on its own merits instead, with the tag removed.
        if it.get("companies") or not it.get("wl_company"):
            return "S1"
        untagged = dict(it)
        untagged["tags"] = re.sub(r"WATCHLIST\s*[—–-][^|\]]*", " ",
                                  it.get("tags", ""), flags=re.IGNORECASE)
        base = _classify(untagged, company_phrases)
        if base == "S1":
            return None
        # Every check from here on must use the STRIPPED tags, not the
        # original. This was the actual mechanism behind most of the real
        # Bali leaks: a rejected "WATCHLIST — Bharti Axa Life Insurance
        # Company Limited" tag still contains the word "Insurance", and the
        # sector/macro keyword checks below matched against `it["tags"]`
        # (the untouched original) rather than the cleaned version — so an
        # unrelated Bali travel story about "Elite Havens... Estate in Bali"
        # sailed into S2 purely because the REJECTED tag text happened to
        # contain a sector word the reader never sees.
        it = untagged
    text = f'{it["tags"]} {it["source"]} {it["title"]} {it["summary"]}'.lower()
    # Sport, entertainment and stray CRA press pages are never rescued by a
    # keyword — those drops are absolute.
    if _NEVER_RELEVANT_RE.search(text) or _is_cra_announcement(it):
        return None
    # Debenture/NCD redemption notices for a non-watchlist issuer are pure
    # procedural housekeeping, never sector or macro news -- but some
    # exchange feed entries list several issuers at once ("...redemption
    # for the following companies:"), which trips _SECTOR_WIDE_RE's plural
    # "companies"/"issuers" wording and rescued them into S3 via the
    # bond-market keyword match below. Checked unconditionally, before that
    # rescue path, so wording can't route it around the drop.
    if _PROCEDURAL_REDEMPTION_RE.search(text) and not it.get("companies"):
        return None
    # Entity-specific stories never reach S2/S3 — checked BEFORE the keyword
    # rules, because instrument words ("commercial paper", "NCD") are also
    # bond-market/macro keywords and were pulling single-issuer allotments
    # into every reader's S3.
    if _ENTITY_STORY_RE.search(text) and not _SECTOR_WIDE_RE.search(text):
        return "S1" if it.get("companies") else None
    # Console keywords are matched on the HEADLINE (plus tags), never the
    # RSS summary. A summary is a paragraph of loose context: one stray
    # word in it was routing whole stories into a section they had nothing
    # to do with — "insurance" in a hospital chain's capex blurb sent
    # Medicover Hospitals to S2, "brokerage" in a derivatives blurb sent a
    # Kalyan Jewellers F&O story there too. If a story is genuinely ABOUT a
    # sector, the sector shows up in its headline.
    headline = f'{it["tags"]} {it["title"]}'.lower()
    if _kw_hit(headline, macro_kw):
        return "S3"
    # A sector's keywords define what is relevant FOR THAT SECTOR. Checked
    # before deferring to `base`, because the built-in relevance gate is
    # BFSI-specific: it requires a bank/NBFC/RBI signal, so genuine news for
    # any other sector ("Road EPC order inflows surge as NHAI awards HAM
    # projects") would otherwise be discarded as having no financial signal
    # before the sector logic ever saw it.
    if sectors and any(_kw_hit(headline, kws) for kws in sectors.values()):
        return "S2"
    if base is None:
        return None
    mapped = _TEAM_SECTION_MAP.get(base)
    # _classify()'s old-S3 (regulatory) bucket is also where a policy-RATE
    # decision lands, because its source-based shortcut fires on ANY item
    # whose source starts with "rbi" — a monetary-policy release and a
    # supervisory circular share a feed but not a category. "RBI keeps repo
    # rate unchanged" is MACRO (S3 in the three-section scheme: RBI's own
    # policy-rate action moves every rate in the system), not sector-desk
    # regulation. Only overridden when the headline itself names a rate/
    # monetary-policy topic — an ordinary RBI circular still maps to S2.
    # Same reasoning extended to bond/money-market AUCTION content: "RBI"-
    # or regulator-sourced items land in old-S3 by source alone before their
    # content is examined, so a G-Sec auction-result release ("Government
    # Stock - Full Auction Results") mapped to S2 even though it is
    # aggregate debt-market data, not sector regulation. Guarded on NOT
    # being a regulatory ACTION headline ("SEBI tightens disclosure norms
    # for debenture trustees") — a regulator's circular ABOUT bonds is
    # still sector regulation (S2), exactly as _classify() itself already
    # distinguishes for the five-section report.
    if (mapped == "S2" and not _REG_ACTION_RE.search(headline)
            and (_S5_RE.search(headline) or _S4_RE.search(headline))):
        mapped = "S3"
    # Final gate, applied to SECTOR routing only. _classify() reads the
    # summary as well as the headline — right for the 7:30 report, wrong
    # for a section everyone receives: a hospital chain's capex note whose
    # blurb mentioned "insurance", and a UK accounting tie-up whose blurb
    # mentioned "asset management", both became BFSI sector news on the
    # strength of one word the reader never sees. If a story is sector
    # news for the whole desk, its own headline says so.
    #
    # Applied to S3 as well, because _classify() matches its bond/macro
    # regexes against the SOURCE NAME too: every item carried by the
    # "Bond Markets" feed hit "bond" in its own feed name and became macro
    # news whatever it said, so private-equity healthcare deals landed in
    # everyone's S3. The one exception is an official statistics feed
    # (RBI-DBIE, MOSPI, PIB, macro-release): those publish nothing BUT
    # macro data, so the source genuinely is the justification and their
    # headlines legitimately carry no sector word ("Latest data release on
    # money supply and reserves"). A keyword-query feed's name is not
    # evidence of anything.
    if mapped in ("S2", "S3"):
        trusted_macro_source = it.get("source", "").lower().startswith(_S5_SOURCES)
        if not trusted_macro_source and not (_FI_SIGNAL_RE.search(headline)
                                             or _S4_RE.search(headline)
                                             or _S5_RE.search(headline)):
            return "S1" if it.get("companies") else None
    return mapped


# ---------------------------------------------------------------------------
# AI classification (Claude Sonnet 5, high effort)
# ---------------------------------------------------------------------------
# The mechanical rules above stay in place as a pre-filter — sport/crypto/
# geography/stock-move/junk/procedural-listing drops are unambiguous and
# free, and the golden set locks in every previously reported leak. What
# kept needing a new regex every round was a genuine JUDGEMENT call: is this
# story about ONE entity, a whole SECTOR, or the MACRO economy? That is
# exactly the kind of call a model is better at than an ever-growing
# pattern list, so it now makes the final S1/S2/S3/drop decision for
# whatever survives the mechanical pre-filter. If the API is unavailable or
# a batch errors, that batch silently falls back to _classify_team so a
# quota outage never blocks the mail.
_AI_MODEL = "claude-sonnet-5"

# 7:40 is the free, no-API system; AI was layered on top later. With no
# credits on the account, every AI stage failed on each run — ~45 doomed
# HTTP calls per send — and, worse, the review pass fails OPEN, so
# near-duplicate removal silently did nothing while appearing to run.
# When this is off the mechanical path (the one the 78-case golden suite
# actually covers) is the real path, not an accident of API failure.
# Flipped from team.json: {"use_ai": true} re-enables everything.
_AI_ENABLED = False


def _ai_on() -> bool:
    return _AI_ENABLED and bool(os.environ.get("ANTHROPIC_API_KEY", ""))
_AI_BATCH_SIZE = 40


def _ai_msg_text(message) -> str:
    """Join text blocks, skipping thinking blocks newer models emit first.
    A local copy, not an import from send_credit_report.py — that module
    imports FROM this file, so the dependency only ever runs one way."""
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text")


def _ai_batch_prompt(batch: list[dict], sectors: dict, macro_kw: list[str]) -> str:
    sector_lines = "\n".join(
        f"  - {name}: {', '.join(kws) if kws else '(no keywords yet — judge by subject matter)'}"
        for name, kws in sectors.items()
    ) or "  (none configured)"
    macro_line = ", ".join(macro_kw) if macro_kw else "(none configured — judge by subject matter)"
    items_block = "\n".join(
        f'{i}. TITLE: {it["title"]}\n'
        f'   SOURCE: {it["source"]}\n'
        f'   SUMMARY: {(it.get("summary") or "")[:220]}\n'
        f'   MATCHED_WATCHLIST_ENTITIES: {", ".join(it.get("companies") or []) or "(none)"}'
        for i, it in enumerate(batch)
    )
    return f"""You are the classifier for an internal credit-desk news digest with exactly three sections:

S1 — WATCHLIST ENTITY NEWS. A story about ONE specific company/entity: its
own results, its own debt issuance/redemption, its own rating action, its
own board appointment, its own M&A/partnership/buyback, an insolvency or
tribunal matter naming it, etc. Only valid when the item's
MATCHED_WATCHLIST_ENTITIES is non-empty — classify as S1 only for an item
that already has a matched entity; if a story is clearly single-entity but
MATCHED_WATCHLIST_ENTITIES is empty, the entity isn't tracked — output DROP.

S2 — SECTOR NEWS. A story about a SECTOR or the industry as a whole, not
one company: regulatory circulars/directions covering an industry, sector
credit-growth or asset-quality data, industry-wide trends, consolidation
across a sector.

  IMPORTANT — a REGULATOR'S OWN ACTION is always S2, even when it names a
  single institution. An RBI/SEBI/IRDAI/NHB penalty, licence cancellation,
  business restriction, or a direction issued under a named statute (e.g.
  "RBI imposes monetary penalty on <one co-operative bank>", "Directions
  under Section 35A of the Banking Regulation Act") is supervisory news the
  whole desk needs — it signals the regulator's posture. Do NOT drop these
  as single-entity stories. (If the named institution is also on the
  watchlist, S1 wins.)

Pick the single best-matching sector from this list using
its keywords as a guide (a story can qualify for a sector even without a
literal keyword hit, if it is clearly about that sector's business):
{sector_lines}

S3 — MACROECONOMIC & MARKETS NEWS. SYSTEMIC economy-wide developments only —
not a dumping ground for anything with a rupee sign in it. India macro (GDP,
CPI/WPI/IIP, PMI, fiscal deficit, GST/tax collections, trade, monsoon/rural
economy, capex/consumption indicators); rates & liquidity (RBI monetary
policy, repo rate, banking-system liquidity, VRR/VRRR); fixed income/credit
markets in AGGREGATE (G-sec yields, systemic bond spreads, foreign debt
flows — NOT one company's own CP/NCD issue, which is S1/DROP per the rule
below); FX & commodities with a credit-relevant India angle (rupee, DXY,
crude, gold); global macro (Fed/ECB/BoE, US data, China growth,
geopolitics/crude shocks) ONLY when it has a plausible India/credit
transmission channel — a global story with no such link is DROP, not S3.
Guide keywords: {macro_line}

  IMPORTANT — insurance/IRDAI news is S2 (Insurance is a BFSI subsector),
  never S3, even though it is "regulatory."

  IMPORTANT — a macro STATISTIC (CPI/WPI/IIP/GDP/PMI) must be the LATEST
  available release or a genuine revision/policy development. If the item
  is plainly discussing an old reference period re-surfacing in today's
  results (e.g. a January inflation writeup appearing in an August feed,
  with no sign it is today's release or a fresh revision), output DROP —
  do not present stale data as current.

DROP — anything that is none of the above, or is not real news. Be
AGGRESSIVE here; a section with 20 low-value items crowding out one real
regulatory story is a worse outcome than an empty section. Always drop:
  - stock-price moves, broker buy/sell/target-price calls or forecasts
    ("X sees..."), technical-analysis/chart noise, IPO listing-pop
    commentary, mutual-fund scheme/NAV pages, F&O/derivatives tables
  - tribunal cause-list or recovery-officer procedural notices
  - sport (scores, fixtures, tournaments), entertainment/celebrity content,
    TRAVEL/TOURISM/HOSPITALITY content (hotels, resorts, destinations,
    festivals, religious rituals) — these carry no finance signal no matter
    what proper noun or place name happens to appear in them
  - financial DATA/quote pages that are not articles: stock-quote pages,
    options-chain/derivatives pricing pages, "52-week high" listicles
  - HR/headcount scraper pages, crypto-trading stories, generic
    personal-finance explainers with no new development
  - a headline that is a mid-sentence fragment, a scraped table/list
    remnant, or otherwise not a real, understandable headline — if you
    cannot tell what the story is about from the title, DROP it rather
    than guess
  - a story naming a rating agency where the agency's own name is the only
    finance signal (a rating action on an untracked, non-financial-sector
    issuer is DROP; the same action on a tracked entity or a genuine
    BFSI/financial issuer is not)
  - one company's OWN CP/NCD/bond issuance, redemption or board approval to
    raise funds — this is S1 (if tracked) or DROP (if not), never S3 macro,
    UNLESS the story is explicitly about a sector- or market-wide funding
    trend (e.g. "NBFC sector CP issuance hits a 3-year high")
  - overseas corporate/PE transactions with no India credit angle
  - a routine appointment/recruitment story with no systemic significance

Rules:
- A story about ONE company's OWN commercial activity (results, debt
  issue, M&A, partnership, buyback, appointment) is S1 (if tracked) or
  DROP (if not) — NEVER S2, even if the company operates in a sector, and
  even if it happens to mention sector-wide vocabulary. This does NOT
  apply to regulator enforcement/directions, which stay S2 per above.
- A rating-agency name (CRISIL, ICRA, CareEdge, India Ratings) is not by
  itself a sector signal — judge the actual subject.
- Before accepting ANY item into S2, confirm it is MATERIALLY about Indian
  BFSI, Indian financial regulation, Indian financial-markets regulation,
  or an identifiable BFSI subsector (banks/NBFCs, microfinance/retail
  credit, insurance, capital markets/AMC/AIF, fintech/payments) — a
  coincidental keyword match is not enough; you must be able to say WHICH
  of these subsectors the story concerns.
- When genuinely uncertain between two sections, prefer the more specific
  one (S1 over S2, S2 over S3) if a legitimate case exists; otherwise DROP
  rather than guess.

Items to classify (0-indexed):
{items_block}

Respond with ONLY a JSON array, one object per item in the same order, no
markdown fences, no commentary:
[{{"i": 0, "section": "S1"}}, {{"i": 1, "section": null}}, ...]
section must be exactly "S1", "S2", "S3", or null (for DROP)."""


def _ai_classify_batch(batch: list[dict], client, sectors: dict,
                        macro_kw: list[str]) -> dict[int, str] | None:
    """Returns {index: section_or_None} for this batch, or None on any
    failure (caller falls back to the mechanical classifier for the whole
    batch — a partial/malformed AI response is treated as a full failure
    rather than guessed at)."""
    try:
        msg = client.messages.create(
            model=_AI_MODEL,
            max_tokens=8000,
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": _ai_batch_prompt(batch, sectors, macro_kw)}],
        )
        text = _ai_msg_text(msg).strip()
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        out = {}
        for row in parsed:
            i, sec = row.get("i"), row.get("section")
            if not isinstance(i, int) or i not in range(len(batch)):
                continue
            out[i] = sec if sec in ("S1", "S2", "S3") else None
        if len(out) != len(batch):
            return None  # incomplete response — don't trust a partial batch
        return out
    except Exception as exc:
        print(f"[ai_classify] batch of {len(batch)} failed, falling back to rules: {exc}")
        return None


_REVIEW_BATCH_SIZE = 20


def _ai_review_batch(batch: list[dict], client) -> dict | None:
    """{index: 'keep'|'wrong_entity'|dup_index}. None on any failure."""
    lines = []
    for i, it in enumerate(batch):
        ent = ", ".join(it.get("companies") or []) or "(none)"
        lines.append(f'{i}. [{it.get("section")}] TITLE: {it["title"]}\n'
                     f'   TAGGED_ENTITY: {ent}\n'
                     f'   SOURCE: {it["source"]}')
    prompt = f"""Review these credit-desk news items for two specific faults.

1. WRONG ENTITY — the item is filed under TAGGED_ENTITY but the story is
   not actually about that entity. This happens when a short name is a
   substring of a longer one (a Reserve Bank of India story filed under
   "Bank of India"), or when a search returned an unrelated company. Being
   *related* is not wrong; only flag it when the story genuinely is not
   about the tagged entity. Items with TAGGED_ENTITY "(none)" cannot be
   wrong_entity.

2. DUPLICATE — the item reports the SAME underlying event as an earlier
   item in this list, just reworded or from another outlet. Two different
   events at the same company are NOT duplicates. Two different companies
   are never duplicates. Point to the LOWEST index of that event.

Items:
{chr(10).join(lines)}

Respond with ONLY a JSON array, one object per item, same order, no
markdown fences:
[{{"i":0,"v":"keep"}},{{"i":1,"v":"wrong_entity"}},{{"i":2,"v":"dup","of":0}}]
Use "keep" whenever you are unsure — keeping a borderline item is much
better than hiding a real one."""
    try:
        # max_tokens must cover thinking tokens too — at 3000 with high
        # effort two live batches burned the budget reasoning and returned
        # no text at all ("Expecting value: line 1 column 1").
        # High effort, matching the router. This pass decides whether a
        # story is a duplicate or a wrong entity match — judgement calls
        # where a cheap answer costs a real item or leaves a repeat in.
        msg = client.messages.create(
            model=_AI_MODEL, max_tokens=8000,
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"^```(json)?|```$", "", _ai_msg_text(msg).strip(),
                      flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        out = {}
        for row in parsed:
            i, v = row.get("i"), row.get("v")
            if not isinstance(i, int) or i not in range(len(batch)):
                continue
            if v == "wrong_entity":
                out[i] = "wrong_entity"
            elif v == "dup":
                of = row.get("of")
                out[i] = of if isinstance(of, int) and 0 <= of < i else "keep"
            else:
                out[i] = "keep"
        return out if len(out) == len(batch) else None
    except Exception as exc:
        print(f"[ai_review] batch failed, keeping all {len(batch)}: {exc}")
        return None


def _ai_review_items(items: list[dict]) -> list[dict]:
    """Second AI pass: drop wrong entity matches and near-duplicate stories.

    Routing is deliberately NOT decided here — S1 pinning already settled
    that. This pass only removes items that are demonstrably wrong or
    redundant, and it fails open: any error, malformed answer, or
    uncertainty keeps the item. It also refuses to empty a section, so a
    bad answer can never wipe out somebody's S1.
    """
    if not _ai_on() or not items:
        return items
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=60, max_retries=1)
    except Exception:
        return items

    # Batches are fixed 20-item slices of `items`, which arrives in raw
    # fetch order (source by source) — NOT grouped by topic. Two "Tata Sons
    # remains an upper-layer NBFC" paraphrases from different outlets can
    # land 40+ items apart purely because of which source returned first,
    # so they were never in the same batch and the model never got the
    # chance to compare them (reported: repeated upper-layer-NBFC stories
    # surviving in S2). Sorting within each section by a topic key first —
    # same section, same lead subject word, shared significant tokens —
    # clusters near-duplicates next to each other before slicing, so a
    # 20-item batch is far more likely to actually contain the pair.
    def _topic_key(it):
        toks = _title_toks(it["title"])
        return (it.get("section") or "", _lead_tok(it["title"]), tuple(sorted(toks)))

    ordered = sorted(items, key=_topic_key)

    drop_wrong, drop_dup = set(), set()
    for start in range(0, len(ordered), _REVIEW_BATCH_SIZE):
        batch = ordered[start:start + _REVIEW_BATCH_SIZE]
        verdicts = _ai_review_batch(batch, client)
        if not verdicts:
            continue
        for i, v in verdicts.items():
            it = batch[i]
            if v == "wrong_entity":
                drop_wrong.add(id(it))
            elif isinstance(v, int):
                keeper = batch[v]
                if keeper.get("section") == it.get("section"):
                    drop_dup.add(id(it))
                    src = it.get("source", "")
                    if src and src not in keeper.setdefault("also", []) \
                            and src != keeper.get("source"):
                        keeper["also"].append(src)

    doomed = drop_wrong | drop_dup
    if not doomed:
        print("[ai_review] nothing flagged")
        return items
    kept = [it for it in items if id(it) not in doomed]
    # A section must never be emptied by this pass — if the model flagged
    # everything in one, that is far likelier to be a bad answer than a
    # genuinely empty section, so leave that section untouched.
    for sec in {it.get("section") for it in items}:
        before = [it for it in items if it.get("section") == sec]
        after = [it for it in kept if it.get("section") == sec]
        if before and not after:
            print(f"[ai_review] refusing to empty {sec} — keeping all {len(before)}")
            kept.extend(before)
    for it in items:
        if id(it) in drop_wrong:
            print(f"[ai_review] wrong entity match: {it['title'][:70]}")
    print(f"[ai_review] dropped {len(drop_wrong)} wrong matches, "
          f"{len(drop_dup)} duplicates; {len(kept)} items remain")
    return kept


# ---------------------------------------------------------------------------
# AI mail-body writing: per-item "why this matters" + per-person exec summary
# ---------------------------------------------------------------------------
_TAKEAWAY_BATCH_SIZE = 25
_SUMMARY_BATCH_SIZE = 15


def _ai_takeaway_batch(items: list[dict], client) -> dict:
    """{item_key: one-line credit angle}. Empty dict on any failure — the
    caller falls back to a bare headline row, exactly today's behaviour."""
    lines = "\n".join(
        f'{i}. [{it.get("section")}] {it["title"]} ({it["source"]})'
        for i, it in enumerate(items)
    )
    prompt = f"""For each numbered news item below, write ONE short clause (under 16
words) explaining why it matters to a credit/BFSI desk — the credit,
regulatory, or market angle. Do not restate the headline. Do not use
filler like "this is important because". Be specific and concrete.

Items:
{lines}

Respond with ONLY a JSON array, same order, no markdown fences:
[{{"i": 0, "why": "..."}}, {{"i": 1, "why": "..."}}, ...]"""
    try:
        msg = client.messages.create(
            model=_AI_MODEL, max_tokens=6000,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"^```(json)?|```$", "", _ai_msg_text(msg).strip(),
                      flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        out = {}
        for row in parsed:
            i, why = row.get("i"), row.get("why")
            if isinstance(i, int) and 0 <= i < len(items) and isinstance(why, str) and why.strip():
                out[_key(items[i])] = why.strip().rstrip(".")
        return out
    except Exception as exc:
        print(f"[ai_takeaway] batch of {len(items)} failed (non-fatal): {exc}")
        return {}


# Fixed taxonomy for key_credit_variable_affected -- every S1 row's AI
# analysis (and the mechanical fallback) tags one of these, so a reader
# scanning the table can filter/scan by what actually moved rather than
# reading every sentence to find out.
_CREDIT_VARIABLES = ["capital", "leverage", "liquidity", "asset_quality",
                     "profitability", "growth", "funding", "governance",
                     "regulatory", "macro", "other"]
_VARIABLE_LABELS = {v: v.replace("_", " ").upper() for v in _CREDIT_VARIABLES}


def _ai_s1_view_batch(items: list[dict], client) -> dict:
    """{item_key: {variable, implication, why, commentary}} for the S1
    table's Summary column. Unlike _ai_takeaway_batch (one clause, only
    for a section's top 3), this covers every S1 row, because the table
    format dropped the hero-card treatment that used to carry a
    headline's weight visually — the Summary column now has to do real
    credit analysis, not repeat the headline or the feed's own summary.
    Empty dict on any failure — caller falls back to _mech_s1_view,
    which returns the same shape mechanically."""
    lines = "\n".join(
        f'{i}. {it["title"]} — {(it.get("summary") or "").strip()[:200]} ({it["source"]})'
        for i, it in enumerate(items)
    )
    var_list = ", ".join(_CREDIT_VARIABLES)
    prompt = f"""You are a credit analyst writing the Summary column of a rated-entity
watchlist table. For each numbered news item below, produce a
structured credit read:

- credit_implication: ONE sentence stating what actually happened and
  what it implies for the entity's credit profile. No headline restatement.
- why_rating_analyst_should_care: ONE sentence on why a rating analyst
  should care -- the mechanism (e.g. "raises near-term refinancing risk
  if repeated" / "modest, unlikely to move the rating on its own"), or
  state plainly it is routine/neutral if that's the honest read.
- key_credit_variable_affected: exactly one of [{var_list}] -- the
  single variable most affected. Use "other" only when none genuinely fits.
- newsletter_commentary: the two sentences above, combined into one
  reader-facing note (25-45 words), which is what actually gets printed.

Do NOT invent facts, numbers, or outcomes not implied by the item. If an
item is genuinely thin (e.g. a bare appointment notice), it is fine for
why_rating_analyst_should_care to say there is no further detail rather
than speculating.

Items:
{lines}

Respond with ONLY a JSON array, same order, no markdown fences:
[{{"i": 0, "credit_implication": "...", "why_rating_analyst_should_care": "...",
"key_credit_variable_affected": "...", "newsletter_commentary": "..."}}, ...]"""
    try:
        msg = client.messages.create(
            model=_AI_MODEL, max_tokens=10000,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"^```(json)?|```$", "", _ai_msg_text(msg).strip(),
                      flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        out = {}
        for row in parsed:
            i = row.get("i")
            commentary = row.get("newsletter_commentary")
            if not (isinstance(i, int) and 0 <= i < len(items)
                    and isinstance(commentary, str) and commentary.strip()):
                continue
            variable = str(row.get("key_credit_variable_affected") or "other").strip().lower()
            if variable not in _CREDIT_VARIABLES:
                variable = "other"
            out[_key(items[i])] = {
                "variable": variable,
                "implication": (row.get("credit_implication") or "").strip(),
                "why": (row.get("why_rating_analyst_should_care") or "").strip(),
                "commentary": commentary.strip(),
            }
        return out
    except Exception as exc:
        print(f"[ai_s1_view] batch of {len(items)} failed (non-fatal): {exc}")
        return {}


# ---------------------------------------------------------------------------
# GPT (OpenAI) credit analysis -- S1 Summary + email body ONLY.
#
# Scope, per explicit instruction: GPT does NOT collect news, does NOT
# classify S1/S2/S3, does NOT touch newsletter formatting. It is a second
# analysis provider layered on top of the EXISTING pipeline, reading
# already-collected/filtered/deduped items and writing into the SAME two
# insertion points the Anthropic path already uses:
#   - section_takeaways[item_key] -> _np_s1_row's `view`   (S1 Summary column)
#   - exec_summary / watchlist_html -> _np_partc            (email body)
# No changes to _np_s1_row, the S1 table structure, or S2/S3 rendering.
# One request per run (not per article) -- see _gpt_analysis.
# ---------------------------------------------------------------------------

# Provider-agnostic: any OpenAI-compatible endpoint works via the same
# `openai` client, just a different base_url/key/model. Prefers Gemini's
# free tier (GEMINI_API_KEY) since that's what's actually configured;
# OPENAI_API_KEY still works as a paid alternative if ever set instead.
_GPT_PROVIDERS = {
    "gemini": {
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        # gemini-2.0-flash was retired by Google (confirmed via a live
        # 404 on 2026-08-20: "no longer available, use
        # models/gemini-3.6-flash"). Overridable via GEMINI_MODEL if
        # Google moves the goalposts again.
        "default_model": "gemini-3.6-flash",
        "model_env": "GEMINI_MODEL",
    },
    # Groq is OpenAI-API-compatible, so it needs no client changes -- only
    # a base_url swap, same as Gemini. Kept BELOW Gemini deliberately: it
    # serves open-weight models, which are weaker at the credit-transmission
    # reasoning the S2/S3 spec asks for, and its per-minute token limits are
    # tighter than Gemini's -- a concern now that S1 runs ~9 concurrent
    # batches. It earns its place as failover, not as the primary engine.
    # GROQ_MODEL must be set to a model the account actually serves; the
    # default here is a guess and will 404 if that model has been retired
    # (exactly how gemini-2.0-flash broke this pipeline once before).
    "groq": {
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "model_env": "GROQ_MODEL",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "base_url": None,  # openai package default
        "default_model": "gpt-4o",
        "model_env": "OPENAI_MODEL",
    },
}


def _gpt_providers() -> list[dict]:
    """Every configured provider, in preference order (Gemini, Groq,
    OpenAI). Empty when none is configured.

    Returns a LIST, not just the first match: a single-provider lookup
    meant that when Gemini returned 503 "high demand" -- observed live --
    the whole edition fell back to mechanical placeholder text even
    though another provider was configured and idle. Callers walk this
    list so a provider outage costs a retry, not the day's analysis."""
    out = []
    for name, cfg in _GPT_PROVIDERS.items():
        key = os.environ.get(cfg["env_key"], "").strip()
        if key:
            # "or default", NOT os.environ.get(name, default): an unset
            # GitHub Actions `vars.X` is injected as an EMPTY STRING, not
            # left absent, so .get()'s default never fires and the model
            # resolved to "" -- every call then 404'd with "The model ``
            # does not exist". Observed live on the first Groq run.
            out.append({**cfg, "name": name, "api_key": key,
                        "model": os.environ.get(cfg["model_env"], "").strip()
                                 or cfg["default_model"]})
    return out


def _gpt_provider() -> dict | None:
    """First configured provider, Gemini preferred. None if none is set."""
    providers = _gpt_providers()
    return providers[0] if providers else None


# S2/S3 are sent only as context for the email body's cross-cutting
# takeaways, never for per-item S2/S3 analysis (out of scope this phase).
# Capped so the daily payload stays a reasonable size on the heaviest days.
_GPT_S1_CAP = 400
_GPT_S2S3_CAP = 40

_GPT_CREDIT_VIEWS = {"Positive", "Negative", "Neutral", "Mixed", "Monitor"}
_GPT_ACTIONS = {"Immediate Review", "Seek Management Clarification",
                "Review", "Monitor", "No Action"}

_GPT_SYSTEM_PROMPT = """You are an experienced Indian BFSI credit-rating analyst supporting an internal CareEdge-style daily credit-intelligence newsletter.
News has already been collected. Do not summarise news mechanically.
Assess each development through:
Event
-> credit transmission
-> affected entity/sector
-> affected credit variable
-> materiality
-> analyst action.
Focus on:
- asset quality
- capitalisation
- leverage
- liquidity
- ALM
- funding
- borrowing cost
- profitability
- growth
- governance
- regulation
- competitive intensity.
Do not automatically treat debt raising as negative.
Do not automatically treat growth as positive.
Do not invent facts, numbers, ratios or company information.
Where evidence is insufficient, say Monitor rather than forcing a directional conclusion.
Differentiate factual information supplied in the news from analytical inference."""


def _gpt_on() -> bool:
    return _gpt_provider() is not None


def _gpt_item_payload(it: dict) -> dict:
    comps = sorted(it.get("companies") or [])
    entity = comps[0] if comps else (it.get("wl_company") or "")
    return {
        "entity": entity,
        "headline": it.get("title", ""),
        "existing_summary": it.get("summary", ""),
        "source": it.get("source", ""),
        "url": it.get("url", ""),
        "published_at": it.get("pub", ""),
    }


def _gpt_s1_payload_indexed(s1_items: list[dict], article_texts: dict | None = None) -> list[dict]:
    """S1 payload rows carry their own list index ("i"). GPT references
    these indices in item_indices so the mapping back to raw items is
    exact, not a guess by company name. Reported bug: mapping purely by
    entity applied ONE synthesised observation (a fundraising story) to
    EVERY item under that company, including an unrelated CFO-appointment
    story -- three different events all showed identical commentary.

    article_texts: {id(item): text} from _gpt_fetch_article_texts, for
    whichever items were fetched. Empty string for the rest -- GPT still
    gets headline+existing_summary either way, article_text is additive."""
    article_texts = article_texts or {}
    out = []
    for i, it in enumerate(s1_items):
        row = _gpt_item_payload(it)
        row["i"] = i
        row["article_text"] = article_texts.get(id(it), "")
        out.append(row)
    return out


# Fetching every S1 item's full article page would take far too long on a
# heavy day (200+ items x several seconds each) -- bounded to the
# highest-priority items by materiality, fetched concurrently so the total
# wait stays reasonable regardless of how many items are eligible.
# Raised 40 -> 120: only the top 40 by materiality got real article text, so
# the other ~200+ S1 items were analysed from a headline plus a 220-char feed
# snippet -- structurally why so much S1 analysis read thin even when Gemini
# did write it. Affordable now that the S1 analysis call is batched (each
# batch carries only its own slice's article text, so per-call input stays
# roughly where it was), and the fetch itself is concurrent.
_GPT_ARTICLE_FETCH_CAP = 120
_GPT_ARTICLE_FETCH_TIMEOUT = 6
_GPT_ARTICLE_TEXT_CAP = 2500
# S1 items per Gemini call. Measured directly: a single call sent 266 S1
# items and got back exactly 100 entries -- no max_tokens was set, so the
# response was being truncated at the API default and everything past
# ~entry 100 was silently never written, however emphatically the prompt
# demanded full coverage. Batching keeps each response comfortably inside
# the output budget; batches run concurrently so wall-clock stays ~one call.
#
# 70 was the first attempt and was still too big: two of four batches hit
# the 16k cap (finish_reason=length) and, because a truncated response is
# invalid JSON, lost ALL their entries rather than just the tail. Measured
# ~230 output tokens per S1 entry, so 30 items/batch lands around 7k --
# comfortably inside the cap with roughly 2x headroom for a verbose day.
_GPT_S1_BATCH = 30
_GPT_MAX_OUTPUT_TOKENS = 16000


def _gpt_fetch_article_text(url: str) -> str:
    """Best-effort full article text for one URL. Empty string on any
    failure (paywall, timeout, non-HTML, blocked) -- caller treats that
    exactly like an item that was never selected for fetching."""
    if not url:
        return ""
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=_GPT_ARTICLE_FETCH_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        # Boilerplate ("Subscribe now", nav links) tends to be short;
        # requiring real sentence length is a cheap, effective filter.
        text = " ".join(p for p in paras if len(p) > 40)
        return text[:_GPT_ARTICLE_TEXT_CAP]
    except Exception:
        return ""


def _gpt_fetch_article_texts(items: list[dict]) -> dict:
    """{id(item): text}, fetched concurrently. Items with no URL or a
    failed fetch are simply absent -- callers already default to ""."""
    candidates = [it for it in items if it.get("url")]
    if not candidates:
        return {}
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(_gpt_fetch_article_text, it["url"]): it for it in candidates}
        # requests' timeout is a per-read-chunk timeout, not a total-time
        # cap -- a pathologically slow response can still take far longer
        # than _GPT_ARTICLE_FETCH_TIMEOUT to finish. Bound .result() too
        # so one stuck request can't block the whole batch indefinitely.
        for fut in futures:
            it = futures[fut]
            try:
                text = fut.result(timeout=_GPT_ARTICLE_FETCH_TIMEOUT + 5)
            except Exception:
                text = ""
            if text:
                out[id(it)] = text
    print(f"[gpt] fetched full article text for {len(out)}/{len(candidates)} "
          f"top-priority S1 items")
    return out


def _gpt_cat_payload_indexed(items: list[dict]) -> list[dict]:
    """S2/S3 payload rows, indexed the same way _gpt_s1_payload_indexed
    indexes S1 -- "category" instead of "entity" (S2/S3 items don't
    belong to one company), no article_text (S1-only for now, to bound
    the number of page fetches per run)."""
    out = []
    for i, it in enumerate(items):
        out.append({
            "i": i,
            "category": it.get("category") or "General",
            "headline": it.get("title", ""),
            "existing_summary": it.get("summary", ""),
            "source": it.get("source", ""),
            "url": it.get("url", ""),
            "published_at": it.get("pub", ""),
        })
    return out


def _gpt_build_payload(s1_items: list[dict], s2_items: list[dict],
                       s3_items: list[dict], today) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """Returns (payload, s1_sent, s2_sent, s3_sent) -- each *_sent list is
    the exact, order-preserved list the "i" indices in the matching
    payload section refer to. Callers must use these (not the original
    *_items lists) when mapping item_indices back to raw items, since
    capping/sorting can reorder/drop entries."""
    s1 = s1_items
    if len(s1) > _GPT_S1_CAP:
        s1 = sorted(s1, key=_materiality, reverse=True)[:_GPT_S1_CAP]
        print(f"[gpt] S1 list capped to top {_GPT_S1_CAP} of {len(s1_items)} "
              f"by materiality for the GPT payload")
    # Full article text for the highest-priority items only (see
    # _GPT_ARTICLE_FETCH_CAP) -- headline + a 200-char snippet alone
    # produces thin, generic analysis for anything not already well-
    # described by the feed. Reported: "can't Gemini summarise the
    # article or give credit implication as required" -- this is what
    # was actually missing; the spec always had an article_text field,
    # it was just never populated.
    fetch_priority = sorted(s1, key=_materiality, reverse=True)[:_GPT_ARTICLE_FETCH_CAP]
    article_texts = _gpt_fetch_article_texts(fetch_priority)
    s2 = _rating_first(s2_items)[:_GPT_S2S3_CAP]
    s3 = _rating_first(s3_items)[:_GPT_S2S3_CAP]
    payload = {
        "date": today.isoformat(),
        "s1": _gpt_s1_payload_indexed(s1, article_texts),
        "s2": _gpt_cat_payload_indexed(s2),
        "s3": _gpt_cat_payload_indexed(s3),
    }
    return payload, s1, s2, s3


def _gpt_salvage_json(text: str):
    """json.loads, falling back to recovering the complete array elements
    from a response truncated mid-write.

    A response cut off at the output cap is invalid JSON, so a plain
    json.loads throws and the entire batch is lost -- including the dozens
    of entries that were written perfectly before the cut. Measured on a
    real run: two batches hit the cap and each lost all ~70 of its items
    when most of them were intact. This walks the text tracking bracket
    depth (string- and escape-aware so braces inside analysis prose don't
    confuse it), finds the end of the last COMPLETE element, and closes
    the structure there."""
    try:
        return json.loads(text)
    except Exception:
        pass
    depth, in_str, esc, last_elem_end = 0, False, False, None
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            # {"s1_summary": [ {...} ]} -- an object closing back to depth
            # 2 is one finished element of the section array.
            if ch == "}" and depth == 2:
                last_elem_end = i
    if last_elem_end is None:
        return None
    for suffix in ("]}", "]"):
        try:
            out = json.loads(text[:last_elem_end + 1] + suffix)
            print(f"[gpt] salvaged {sum(len(v) for v in out.values() if isinstance(v, list))} "
                  f"complete entries from a truncated response")
            return out
        except Exception:
            continue
    return None


def _gpt_validate(data, require_body: bool = True) -> bool:
    """Structural check before anything from this response touches HTML.
    Deliberately strict -- a malformed or partially-hallucinated response
    is treated as a full failure (caller falls back), not patched up.

    require_body=False for the follow-on S1 batches: only the first batch
    is asked for email_body/s2/s3, so the rest legitimately return
    s1_summary alone and must not be failed for the absence."""
    if not isinstance(data, dict):
        return False
    s1 = data.get("s1_summary")
    if not isinstance(s1, list):
        return False
    if require_body:
        eb = data.get("email_body")
        if not isinstance(eb, dict):
            return False
        kt = eb.get("key_takeaways")
        if not isinstance(kt, list):
            return False
        for row in kt:
            if not isinstance(row, dict) or not str(row.get("title") or "").strip() \
                    or not str(row.get("text") or "").strip():
                return False
        wa = eb.get("watchlist_attention", [])
        if not isinstance(wa, list):
            return False
        for row in wa:
            if not isinstance(row, dict) or not str(row.get("entity") or "").strip() \
                    or not str(row.get("text") or "").strip():
                return False
    for row in s1:
        if not isinstance(row, dict) or not str(row.get("entity") or "").strip() \
                or not str(row.get("analysis") or "").strip():
            return False
        if row.get("credit_view") not in _GPT_CREDIT_VIEWS:
            return False
        if row.get("analyst_action") not in _GPT_ACTIONS:
            return False
        idx = row.get("item_indices")
        if not isinstance(idx, list) or not idx \
                or not all(isinstance(x, int) for x in idx):
            return False
    # s2_summary/s3_summary are optional (older prompt versions or a
    # thin news day may omit them entirely) but must be well-formed
    # when present -- same item_indices contract as s1_summary, just
    # no entity/credit_view/analyst_action (S2/S3 items don't belong to
    # one company, and don't get the Positive/Negative directional call
    # S1 does -- just a plain analytical read).
    for section_key in ("s2_summary", "s3_summary"):
        rows = data.get(section_key, [])
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("analysis") or "").strip():
                return False
            idx = row.get("item_indices")
            if not isinstance(idx, list) or not idx \
                    or not all(isinstance(x, int) for x in idx):
                return False
    return True


def _gpt_analysis(s1_items: list[dict], s2_items: list[dict],
                  s3_items: list[dict], today) -> tuple[dict, list[dict], list[dict], list[dict]] | None:
    """Batched requests per run. Returns (validated data dict, s1_sent,
    s2_sent, s3_sent) on success, or None on any failure -- caller falls
    back to the existing Anthropic/mechanical paths exactly as if GPT were
    never called. Each *_sent list is the exact order-preserved list its
    section's item_indices resolve against.

    S1 is split into _GPT_S1_BATCH-sized calls run concurrently and merged
    (see _GPT_S1_BATCH for why). The "i" indices in the payload are global
    positions in s1_sent and are NOT re-based per batch, so merging the
    per-batch s1_summary lists is a plain concatenation -- every index
    still resolves against the same s1_sent list the caller holds.
    Only the first batch is asked for email_body/s2/s3."""
    if not _gpt_on() or not s1_items:
        return None
    import time as _time
    payload, s1_sent, s2_sent, s3_sent = _gpt_build_payload(s1_items, s2_items, s3_items, today)
    providers = _gpt_providers()
    if not providers:
        return None
    provider = providers[0]
    # Which providers are actually reachable this run, primary first. A
    # failover provider only gets exercised when the primary fails a
    # batch, so without this line a correctly-configured key and a
    # missing one look identical in the log on any healthy run.
    print("[gpt] providers configured: "
          + ", ".join(f"{p['name']}({p['model']})" for p in providers))
    t0 = _time.time()
    s1_all = payload.get("s1") or []
    chunks = [s1_all[i:i + _GPT_S1_BATCH]
              for i in range(0, len(s1_all), _GPT_S1_BATCH)] or [[]]
    jobs = []
    for bi, chunk in enumerate(chunks):
        jobs.append((bi, {
            "date": payload["date"],
            "s1": chunk,
            # Only batch 0 carries S2/S3; the others are S1-only so their
            # output budget goes entirely to S1 coverage.
            "s2": payload.get("s2", []) if bi == 0 else [],
            "s3": payload.get("s3", []) if bi == 0 else [],
        }))
    try:
        from openai import OpenAI
        # One client per configured provider, in preference order. A batch
        # walks this list, so a provider that is rate-limited or down costs
        # a retry elsewhere rather than that batch's items -- measured
        # need: a run hit Gemini's free-tier ceiling ("limit: 20" requests
        # /min) and lost a whole batch with no second provider to take it.
        clients = [(p, OpenAI(api_key=p["api_key"], base_url=p["base_url"],
                              timeout=240, max_retries=1))
                   for p in providers]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
            results = list(ex.map(
                lambda job: _gpt_one_call(clients, job[1], job[0] == 0), jobs))
    except Exception as exc:
        print(f"[gpt] analysis failed (non-fatal, falling back to existing pipeline): {exc}")
        return None
    # Batch 0 additionally carries the email body and S2/S3. It used to be
    # treated as all-or-nothing -- if it failed, the whole run fell back to
    # the mechanical pipeline and every other batch's S1 analysis was
    # thrown away with it. Observed live: batch 0 truncated, and an
    # otherwise-good edition went out fully mechanical. Now a failed batch
    # 0 costs only the email body and S2/S3; every S1 batch that succeeded
    # still lands. The run only gives up when NO batch returned anything.
    ok = [r for r in results if r is not None]
    if not ok:
        print("[gpt] analysis failed (non-fatal, falling back to existing pipeline): "
              "no batch returned usable output")
        return None
    if results[0] is not None:
        data = results[0]
        rest = results[1:]
    else:
        print("[gpt] primary batch failed -- keeping S1 analysis from the other "
              "batches, email body and S2/S3 fall back to the mechanical path")
        data = {"email_body": {"key_takeaways": [], "watchlist_attention": []},
                "s1_summary": [], "s2_summary": [], "s3_summary": []}
        rest = results
    data.setdefault("s1_summary", [])
    ok_batches = len(ok)
    for r in rest:
        if r is None:
            continue
        data["s1_summary"].extend(r.get("s1_summary") or [])
    covered = len({i for row in data["s1_summary"]
                   for i in (row.get("item_indices") or [])})
    print(f"[gpt] provider={provider['name']} model={provider['model']} "
          f"elapsed={_time.time() - t0:.1f}s batches={ok_batches}/{len(jobs)} "
          f"s1_sent={len(s1_all)} s1_entries={len(data['s1_summary'])} "
          f"s1_items_covered={covered} "
          f"s2_sent={len(payload.get('s2', []))} s3_sent={len(payload.get('s3', []))}")
    print(f"[gpt] analysis ok: {len(data['s1_summary'])} S1 entries "
          f"(of {len(s1_all)} sent), "
          f"{len(data.get('s2_summary', []))} S2 entries, "
          f"{len(data.get('s3_summary', []))} S3 entries, "
          f"{len(data['email_body'].get('key_takeaways', []))} key takeaways, "
          f"{len(data['email_body'].get('watchlist_attention', []))} watchlist entries")
    return data, s1_sent, s2_sent, s3_sent


def _gpt_retry_after(exc) -> float | None:
    """The provider's OWN suggested retry delay, in seconds, if it gave
    one. Gemini's 429 body carries "Please retry in 1.36394978s" -- a
    fixed 15s/30s backoff both wastes most of that recovery window and
    risks landing the retry inside the same congested minute, so honour
    the server's number when it offers one."""
    m = re.search(r"retry in ([\d.]+)s", str(exc))
    if not m:
        return None
    try:
        # Small pad, and never sit longer than the fixed backoff would.
        return min(float(m.group(1)) + 1.0, 30.0)
    except ValueError:
        return None


def _gpt_one_call(clients: list, payload: dict, with_body: bool):
    """One S1 batch, tried against each configured provider in turn.
    Returns the validated dict, or None once every provider has failed --
    a failed batch costs only its own items' analysis, never the run."""
    import time as _time
    for provider, client in clients:
        out = _gpt_try_provider(client, provider, payload, with_body)
        if out is not None:
            return out
        if len(clients) > 1:
            print(f"[gpt] {provider['name']} failed for this batch, "
                  f"trying the next configured provider")
    return None


def _gpt_try_provider(client, provider: dict, payload: dict, with_body: bool):
    """One S1 batch against ONE provider."""
    import time as _time
    user_prompt = f"""Analyse today's collected news for an internal CareEdge-style credit-intelligence newsletter.

INPUT (JSON):
{json.dumps(payload, ensure_ascii=False)}

INSTRUCTIONS:
- Every item in s1/s2/s3 carries an "i" index, LOCAL to its own section (s1's i values and s2's i values are independent -- an s2_summary entry's item_indices refers to s2's list, never s1's or s3's). Every s1_summary/s2_summary/s3_summary entry MUST include "item_indices": the list of "i" values it covers -- this is how your analysis gets mapped back onto the exact articles it's about. Never guess by company/category alone: an entity or category can have several unrelated stories on the same day (e.g. a fundraising AND a separate CFO appointment), and each needs its OWN item_indices, not a shared one.
- S1 is the tracked watchlist; give each S1 entity/event a detailed analytical read (entity, event, directional credit_view, materiality, analyst_action, analysis, watch -- see schema). Unlike S2/S3, S1 rows are never dropped from the newsletter table -- every S1 item you are shown is going to be displayed regardless, so you MUST return an s1_summary entry covering every single "i" index in the s1 list, with no exceptions. For an item with genuinely no credit signal (routine analyst commentary, recruitment, an incidental mention), still write a real entry: credit_view "Neutral", analyst_action "No Action", materiality low, and a short honest analysis like "Routine brokerage/analyst commentary, no credit implication" or "Recruitment posting, not credit-relevant" -- never omit an S1 item, since omission means the reader sees a generic templated placeholder instead of your judgment.
- S2/S3 "analysis" is a View/Implication, not a second summary: the reader already sees the news summary elsewhere, so do not restate what happened -- answer "what does this specific development change for the credit profile, financial performance, risk profile or operating environment of the affected entity/sub-sector?" Before writing it, work out (silently, don't include this reasoning in the output): the exact event/change; the affected universe (entity-specific / sub-sector / BFSI-wide / macro); which credit-transmission channels are touched (growth/business profile, profitability/margins, asset quality/credit cost, capitalisation, leverage, liquidity/ALM, funding availability/cost, governance, operational/cyber risk, regulatory/compliance risk); direction (Positive/Negative/Mixed/Neutral); materiality (High/Medium/Low); who is most exposed vs relatively insulated; and what's genuinely worth monitoring next, if anything. Then write only the View/Implication itself, grounded in that analysis: explain the transmission mechanism (why and how this affects credit), name the specific type of institution most affected instead of generically saying "lenders"/"banks"/"the sector" unless the whole sector genuinely is affected, use specific numbers from the article where useful but never invent missing data, distinguish fact from inference, and never attribute intention to RBI/SEBI/government/management beyond what the source states. Don't force a directional call where the impact is genuinely uncertain -- say so plainly instead. Avoid generic filler ("will need to be monitored", "could have significant implications", "reflects the evolving landscape", "is a positive development", "will improve the sector") unless immediately followed by the specific causal reason. Normal length is 45-80 words of real analysis; a genuinely low-materiality item only needs 1-2 sentences. No equity/share-price recommendations. No entity/credit_view/analyst_action fields for S2/S3 -- just the "analysis" string itself, held to this bar.
- Before finalising each S2/S3 "analysis", mentally compare it against every other one you're about to output: if two read as substantially similar, ask whether those two articles genuinely share the same credit implication. If not, rewrite the weaker one from that specific article's own facts and transmission mechanism. An analysis that could be pasted under a different article with no meaningful change, that mostly repeats the summary, that names no transmission mechanism, or that reaches for the whole BFSI sector when only a sub-sector is actually affected, has failed and must be rewritten before you include it.
- Genuinely filter S2/S3, not just analyse everything you're given: omit a summary entry entirely for routine market commentary, generic explainers, or anything with no real credit/sector relevance even after a full read -- an item you omit is simply left out of the table entirely, so only include an entry when it is actually worth a reader's attention.
- Two categories are material by default and should not be filtered out just because they lack a rupee figure or a single named company -- that is the wrong bar for S2/S3, which by definition is not about one entity: (a) a named regulator official (RBI/SEBI/IRDAI Governor, Deputy Governor, ED, etc) taking a policy stance on oversight, systemic risk, or rulemaking -- this is regulatory-policy substance, not "commentary", even without a rupee figure attached; (b) sector-wide adoption, volume, or penetration data with a real reported number (transaction value, user/registration count, participation rate) -- this is sector development, not a generic trend piece, even without a single named company driving it.
- If two or more items in the SAME section refer to the SAME underlying event (e.g. two articles both about one fundraising, or two wire reports of the same RBI circular), synthesise them into ONE summary entry with all their "i" values in item_indices. Items about a DIFFERENT event get a SEPARATE entry with their own item_indices -- do not merge unrelated events just because they share a company or category. Sharing a company is NEVER sufficient grounds to merge on its own -- check what each individual item actually says before deciding, every time, even under time/output pressure to cover everything quickly. Concrete example of what NOT to do: three same-day items for one company -- "Company X releases a share pledge", "Company X launches a new investment product", and "Company X's order book grows 100% YoY" -- are THREE separate events (financing/governance, product launch, business performance) and need THREE separate entries with their own item_indices, each actually describing what that specific item says. Writing one merged entry and pointing all three "i" values at it is wrong even if it saves effort -- an entry whose text doesn't match what a specific linked article says is worse than no entry at all, because the reader trusts it as your read of THAT article. This applies with even more force ACROSS different companies: item_indices in one entry must never span more than one company/entity in s1 -- do not build a catch-all entry that lumps several unrelated low-value items from DIFFERENT companies together under one summary as a shortcut to satisfy full coverage. If you have many thin, low-value S1 items, that means many short individual entries (one per item, each correctly describing only that item), not one entry serving several of them. The SAME rule applies identically to s2_summary and s3_summary: two headlines about different regulatory actions, different studies, or different institutions must never share one item_indices entry just because they share a category (e.g. "SEBI derivatives study" and "SEBI bars two players for CAS manipulation" are two unrelated stories and need two separate entries, not one). There is a real, automatic consequence for getting this wrong, in EVERY section (s1/s2/s3 alike): every item_indices list with more than one entry is checked against the OTHER items in it, and any item whose headline doesn't genuinely match gets silently discarded from that entry -- it loses your analysis entirely and shows generic placeholder text (S1) or no analysis at all (S2/S3) instead, EVEN THOUGH you technically included its index. A wrongly-merged entry doesn't just risk being wrong, it actively costs those items their coverage. Writing separate entries for separate stories is the only way to guarantee every item actually keeps the analysis you write for it.
- s1_summary must have exactly one entry's worth of coverage for every "i" in the s1 list (merging same-event duplicates per the rule above is fine, omitting an item is not) -- see the S1 instruction above for how to handle items with no real signal. s2_summary/s3_summary are the opposite: omission there is the filtering mechanism, so exclude recruitment/hiring stories, generic analyst/market commentary that only mentions an entity in passing, incidental keyword matches, and other items with no credible credit/sector implication -- having fewer S2/S3 summary entries than items supplied is expected and correct, and it is fine for s2_summary/s3_summary to be empty arrays on a thin news day.
- For every s1_summary entry, determine: what changed, through which credit variable, the directional implication (Positive/Negative/Neutral/Mixed/Monitor), and the analyst action (Immediate Review/Seek Management Clarification/Review/Monitor/No Action). For fundraising specifically, do not assume it is negative -- the implication depends on instrument, tenor, pricing and use of proceeds; if those are not in the supplied news, say the credit implication depends on those details and recommend Monitor or Review rather than asserting a directional view.
- email_body.key_takeaways must be cross-cutting and prioritised across today's S1/S2/S3 news -- max 4-6 bullets, 1-2 concise sentences each. Do NOT repeat every S1 entity here.
- email_body.watchlist_attention is at most 2-4 entities where genuine analyst action is warranted, drawn from S1 only. Return an empty list if none genuinely qualify.
- The email body and s1_summary must not contain identical text for the same entity: the email is short/prioritised/cross-news, s1_summary is detailed/entity-specific.
- Do not invent facts, numbers, ratios or company financials not present in the supplied news.
- Some S1 items include "article_text": the full scraped article body, not just the headline/existing_summary. When present, ground the analysis in it -- actual instrument details, amounts, tenor, quoted management commentary, etc -- instead of writing generically off the headline alone. When article_text is empty (not every item has it), work from headline + existing_summary as before; do not pretend to know more than what was supplied. S2/S3 items never have article_text -- work from headline + existing_summary only.

- The "i" values in this batch's s1 list are GLOBAL positions and do NOT start at 0 -- use each item's own "i" exactly as given in item_indices. Never renumber them.
{"" if with_body else '- This batch is S1 ONLY. Return "s1_summary" alone: no "email_body", no "s2_summary", no "s3_summary" (they are handled in a separate request and duplicating them here wastes your output budget).'}
- STRONGLY PREFER one s1_summary entry per "i" value, each written about that one article. You have ample output budget for this batch, so there is no reason to lump items together to save space. Merge two indices into a single entry ONLY when both articles genuinely report the SAME underlying event (e.g. two wire reports of one bond issue); never to cover more ground quickly.

Respond with ONLY this JSON structure, no markdown fences, no extra commentary:
{{
{'''  "email_body": {
    "headline": "Daily Credit Intelligence",
    "key_takeaways": [{"title": "...", "credit_view": "Positive|Negative|Neutral|Mixed|Monitor", "text": "..."}],
    "watchlist_attention": [{"entity": "...", "action": "...", "text": "..."}]
  },
''' if with_body else ''}  "s1_summary": [
    {{"entity": "...", "event": "...", "item_indices": [0],
      "credit_view": "Positive|Negative|Neutral|Mixed|Monitor",
      "materiality": "High|Medium|Low",
      "analyst_action": "Immediate Review|Seek Management Clarification|Review|Monitor|No Action",
      "analysis": "...", "watch": "..."}}
  ]{''',
  "s2_summary": [
    {"item_indices": [0], "analysis": "..."}
  ],
  "s3_summary": [
    {"item_indices": [1, 2], "analysis": "..."}
  ]''' if with_body else ''}
}}"""
    t0 = _time.time()
    try:
        # A transient overload (Gemini 503 "high demand", a rate limit) is
        # common enough to be worth a couple of short retries -- confirmed
        # directly: a run that failed outright on a bare call succeeded a
        # few minutes later with no code change. But this must stay
        # bounded, not open-ended: this call sits in the path of the whole
        # team's 7:40 mail, so waiting indefinitely for Gemini to recover
        # would hold every recipient's mail hostage to Google's outage.
        # Three attempts with a short, doubling gap catches the common
        # "back within seconds/tens of seconds" case; anything longer
        # still falls through to the existing mechanical-pipeline fallback
        # below so nobody's mail is ever blocked on this.
        resp = None
        last_exc = None
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=provider["model"],
                    response_format={"type": "json_object"},
                    # Was unset, so the response was capped at the API
                    # default and silently truncated mid-answer -- the
                    # measured cause of S1 coverage stalling at ~100
                    # entries no matter how many items were sent.
                    max_tokens=_GPT_MAX_OUTPUT_TOKENS,
                    messages=[
                        {"role": "system", "content": _GPT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    # Prefer the provider's own hint over the fixed
                    # backoff: a rate-limit that clears in ~1.4s should
                    # not cost 15s, and waiting the full 15/30s can push
                    # the retry into the next congested window anyway.
                    wait = _gpt_retry_after(exc) or 15 * (2 ** attempt)
                    print(f"[gpt] {provider['name']} attempt {attempt + 1}/3 failed "
                          f"({str(exc)[:120]}), retrying in {wait:.1f}s")
                    _time.sleep(wait)
        if resp is None:
            raise last_exc
        finish = getattr(resp.choices[0], "finish_reason", "")
        if finish == "length":
            print(f"[gpt] WARNING: batch hit the {_GPT_MAX_OUTPUT_TOKENS}-token "
                  f"output cap (finish_reason=length) -- some items in this "
                  f"batch will fall back to the mechanical view")
        data = _gpt_salvage_json(resp.choices[0].message.content)
        if data is None:
            print("[gpt] batch response was truncated beyond recovery, skipping this batch")
            return None
        usage = getattr(resp, "usage", None)
        if not _gpt_validate(data, require_body=with_body):
            print("[gpt] batch failed schema validation (non-fatal), skipping this batch")
            return None
        print(f"[gpt] batch ok: {len(data.get('s1_summary') or [])} S1 entries "
              f"of {len(payload.get('s1') or [])} sent in "
              f"{_time.time() - t0:.1f}s, tokens={getattr(usage, 'total_tokens', 'n/a')}")
        return data
    except Exception as exc:
        print(f"[gpt] batch failed (non-fatal): {exc}")
        return None


def _gpt_map_s1(data: dict, s1_sent: list[dict]) -> dict:
    """Maps GPT's s1_summary onto raw S1 items via item_indices (exact,
    deterministic -- see _gpt_analysis/_gpt_validate), in the
    {item_key: {variable, implication, why, commentary}} shape _np_s1_row
    already reads. s1_sent MUST be the same order-preserved list returned
    by _gpt_analysis, not the original unfiltered S1 list, since the
    indices are positions into that exact list.

    Previously matched by entity name alone, which applied ONE
    synthesised observation to EVERY item under that company -- a
    fundraising analysis got copy-pasted onto an unrelated CFO-appointment
    story for the same entity. Indices fix this at the root: each
    s1_summary entry only touches the specific articles it was written
    about."""
    out: dict = {}
    n = len(s1_sent)
    for row in data.get("s1_summary", []):
        idx = [i for i in (row.get("item_indices") or []) if isinstance(i, int) and 0 <= i < n]
        if not idx:
            continue
        credit_view = row.get("credit_view", "Monitor")
        action = row.get("analyst_action", "Monitor")
        analysis = (row.get("analysis") or "").strip()
        watch = (row.get("watch") or "").strip()
        commentary = f"{credit_view} | {action}: {analysis}"
        if watch:
            commentary += f" Watch: {watch}."
        view = {"variable": "other", "implication": analysis,
                "why": watch, "commentary": commentary}
        # Guards a merged entry (one analysis pointed at several items).
        #
        # This previously required >= 2 shared title words after removing
        # the company name, and it was far too strict: measured on a real
        # run it stripped the analysis off 145 S1 items in a single
        # edition. Different write-ups of ONE event routinely share only
        # one word -- "HDFC Bank raises $1.75 billion in biggest overseas
        # fundraise" vs "HDFC Bank gets BBB rating from S&P for $1.75bn
        # bond" share nothing but "bond" once the entity is removed, yet
        # are plainly the same bond issue. Every false drop costs that row
        # its analysis and shows generic placeholder text instead, so at
        # 145/run the guard was doing far more damage than the cross-event
        # bleed it was added to prevent.
        #
        # The bleed it targeted (three unrelated Nisus Finance stories all
        # showing identical text) was driven by output-budget pressure --
        # Gemini lumping items to fit a truncated response. That pressure
        # is gone now that S1 is batched with an explicit token budget and
        # the prompt asks for one entry per item, so merges should be rare
        # and genuine. What remains here is the narrow check for the worst
        # failure only: an entry spanning MORE THAN ONE COMPANY, where the
        # text cannot possibly be right for all of them. Same-company
        # merges are trusted and logged, so a regression is visible in the
        # run log rather than silent.
        if len(idx) > 1:
            anchor_co = (s1_sent[idx[0]].get("companies") or [None])[0]
            kept = [idx[0]]
            for i in idx[1:]:
                other_co = (s1_sent[i].get("companies") or [None])[0]
                if anchor_co and other_co and anchor_co != other_co:
                    print(f"[gpt] dropped cross-company merge: "
                          f"'{s1_sent[i]['title'][:60]}' ({other_co}) merged with "
                          f"'{s1_sent[idx[0]]['title'][:60]}' ({anchor_co}) "
                          f"-- falls back to mechanical view")
                    continue
                kept.append(i)
            if len(kept) > 1:
                print(f"[gpt] merged entry kept for {len(kept)} same-company items: "
                      f"'{s1_sent[idx[0]]['title'][:70]}'")
            idx = kept
        for i in idx:
            out[_key(s1_sent[i])] = view
    return out


def _gpt_map_cat(data: dict, section_key: str, sent: list[dict]) -> dict:
    """Maps GPT's s2_summary/s3_summary onto raw items via item_indices,
    returning {item_key: plain analysis string} -- the shape _np_card's
    `takeaway` param already expects for the existing "Credit lens" line,
    so extending Gemini analysis to S2/S3 needed no new card markup, just
    a second insertion into the same section_takeaways dict S1 uses."""
    out: dict = {}
    n = len(sent)
    for row in data.get(section_key, []):
        idx = [i for i in (row.get("item_indices") or []) if isinstance(i, int) and 0 <= i < n]
        analysis = (row.get("analysis") or "").strip()
        if not idx or not analysis:
            continue
        # Same cross-item merge bug the S1 mapper guards against (see
        # _gpt_map_s1): Gemini sometimes points one item_indices list at
        # several genuinely unrelated S2/S3 headlines and the same analysis
        # text gets stamped onto all of them -- confirmed directly, e.g. a
        # SEBI derivatives-study analysis showing up verbatim under an
        # unrelated "Sebi bars two players... CAS manipulation" headline.
        # Only keep indices whose headline actually overlaps the anchor's.
        if len(idx) > 1:
            anchor_toks = _title_toks(sent[idx[0]]["title"])
            kept = [idx[0]]
            for i in idx[1:]:
                other_toks = _title_toks(sent[i]["title"])
                if anchor_toks and other_toks and len(anchor_toks & other_toks) >= 2:
                    kept.append(i)
                else:
                    print(f"[gpt] dropped merged {section_key} entry for unrelated headline: "
                          f"'{sent[i]['title'][:70]}' doesn't match "
                          f"'{sent[idx[0]]['title'][:70]}' -- falls back to no Gemini analysis")
            idx = kept
        for i in idx:
            out[_key(sent[i])] = analysis
    return out


def _gpt_map_email_body(data: dict) -> tuple[str, str]:
    """Renders GPT's email_body into the two plain-text strings
    _np_partc already accepts (exec_summary, watchlist_html) -- no changes
    to _np_partc's escaping or markup needed for the takeaways themselves."""
    eb = data.get("email_body") or {}
    bits = []
    for kt in (eb.get("key_takeaways") or [])[:6]:
        title = str(kt.get("title") or "").strip()
        view = str(kt.get("credit_view") or "").strip()
        text = str(kt.get("text") or "").strip()
        if not (title and text):
            continue
        bits.append(f"{title} ({view}): {text}" if view else f"{title}: {text}")
    exec_summary = " ".join(bits)

    wa_bits = []
    for wa in (eb.get("watchlist_attention") or [])[:4]:
        entity = str(wa.get("entity") or "").strip()
        action = str(wa.get("action") or "").strip()
        text = str(wa.get("text") or "").strip()
        if not (entity and text):
            continue
        wa_bits.append(f"{entity} ({action}): {text}" if action else f"{entity}: {text}")
    watchlist_html = " ".join(wa_bits)
    return exec_summary, watchlist_html


def _ai_summary_batch(entries: list[tuple], client) -> dict:
    """entries: [(name, [top5 titles])]. Returns {index: summary text}.
    Empty dict on any failure — the caller omits the summary block, exactly
    today's behaviour with no exec summary at all."""
    blocks = []
    for i, (name, titles) in enumerate(entries):
        story_lines = "\n".join(f"   - {t}" for t in titles) or "   - (no fresh items today)"
        blocks.append(f"{i}. Reader: {name or 'the desk'}\n{story_lines}")
    prompt = f"""You write the 2-3 sentence "at a glance" opening paragraph for an
internal credit-desk morning briefing. For EACH reader below, given their
top headlines, write a short executive summary that SYNTHESISES the
themes (e.g. "Two of your NBFCs face rating pressure while the RBI holds
rates steady") rather than listing the headlines back. Plain prose, no
bullets, no bold, third person, confident and factual, under 55 words.
If a reader has no items, write one sentence saying nothing material
came up for their entities/sectors today.

{chr(10).join(blocks)}

Respond with ONLY a JSON array, same order as the readers above, no
markdown fences:
[{{"i": 0, "summary": "..."}}, {{"i": 1, "summary": "..."}}, ...]"""
    try:
        msg = client.messages.create(
            model=_AI_MODEL, max_tokens=6000,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"^```(json)?|```$", "", _ai_msg_text(msg).strip(),
                      flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        out = {}
        for row in parsed:
            i, s = row.get("i"), row.get("summary")
            if isinstance(i, int) and 0 <= i < len(entries) and isinstance(s, str) and s.strip():
                out[i] = s.strip()
        return out
    except Exception as exc:
        print(f"[ai_summary] batch of {len(entries)} failed (non-fatal): {exc}")
        return {}


def _ai_mail_body_content(top5_by_email: dict) -> tuple[dict, dict]:
    """top5_by_email: {email: (name, top5_items)}.

    Batched AI pass over every recipient's Top-5, run ONCE per send (not
    once per person): unique items across all top5 lists get a single "why
    it matters" line each (shared S2/S3 stories are typically in many
    people's top5, so this avoids asking the model the same question 30
    times), and every person gets their own synthesised summary paragraph
    from a batched call over all recipients. Fully fails open: on any
    error, both returned dicts are empty and the mail renders exactly as it
    did before this feature existed.

    Returns (takeaways: {item_key: line}, summaries: {email: paragraph}).
    """
    if not _ai_on() or not top5_by_email:
        return {}, {}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=60, max_retries=1)
    except Exception:
        return {}, {}

    unique_items: dict = {}
    for _name, top5 in top5_by_email.values():
        for it in top5:
            unique_items.setdefault(_key(it), it)
    unique_list = list(unique_items.values())

    takeaways: dict = {}
    for start in range(0, len(unique_list), _TAKEAWAY_BATCH_SIZE):
        takeaways.update(_ai_takeaway_batch(unique_list[start:start + _TAKEAWAY_BATCH_SIZE], client))
    print(f"[ai_takeaway] {len(takeaways)}/{len(unique_list)} unique top-5 items got a credit-angle line")

    emails = list(top5_by_email.keys())
    summaries: dict = {}
    for start in range(0, len(emails), _SUMMARY_BATCH_SIZE):
        chunk = emails[start:start + _SUMMARY_BATCH_SIZE]
        entries = [(top5_by_email[e][0], [it["title"] for it in top5_by_email[e][1]]) for e in chunk]
        result = _ai_summary_batch(entries, client)
        for i, email in enumerate(chunk):
            if i in result:
                summaries[email] = result[i]
    print(f"[ai_summary] {len(summaries)}/{len(emails)} recipients got an executive summary")
    return takeaways, summaries


def _classify_items_ai(items: list[dict], company_phrases: list[str], sectors: dict,
                        macro_kw: list[str]) -> None:
    """Sets it['section'] on every item, in place. AI-first with a
    per-batch mechanical fallback so an API outage degrades, not blocks."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = None
    if _ai_on():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=60, max_retries=1)
        except Exception as exc:
            print(f"[ai_classify] anthropic client unavailable, using rules only: {exc}")
    # S1 is not a judgement call. An item the fetcher tagged to a watchlist
    # entity, or whose text matched one, IS that entity's news by
    # definition — so it is pinned to S1 here and never shown to the model.
    # Leaving it to the model meant a cautious answer could silently empty
    # somebody's S1, which is the one section the desk cannot do without.
    # (Junk, stock moves and procedural noise are already gone by now, so
    # this cannot pin garbage.)
    pinned = [it for it in items if it.get("companies")]
    for it in pinned:
        it["section"] = "S1"
    rest = [it for it in items if not it.get("companies")]
    if pinned:
        print(f"[ai_classify] {len(pinned)} watchlist items pinned to S1 (not sent to the model)")

    if client is None:
        for it in rest:
            it["section"] = _classify_team(it, company_phrases, sectors, macro_kw)
        _tag_categories(items)
        return

    n_ai, n_fallback = 0, 0
    for start in range(0, len(rest), _AI_BATCH_SIZE):
        batch = rest[start:start + _AI_BATCH_SIZE]
        result = _ai_classify_batch(batch, client, sectors, macro_kw)
        if result is None:
            n_fallback += len(batch)
            for it in batch:
                it["section"] = _classify_team(it, company_phrases, sectors, macro_kw)
        else:
            n_ai += len(batch)
            for i, it in enumerate(batch):
                it["section"] = result[i]
    print(f"[ai_classify] {n_ai} items classified by {_AI_MODEL}, "
          f"{n_fallback} fell back to mechanical rules")
    _tag_categories(items)


def _tag_categories(items: list[dict]) -> None:
    """Sets it['category'] for every S2/S3 item, in place. Applied uniformly
    after classification regardless of which path (AI, mechanical fallback,
    or console keyword) decided the section, so the taxonomy label is never
    tied to one classification route."""
    for it in items:
        sec = it.get("section")
        if sec == "S2":
            it["category"] = _categorize(it, _S2_TAXONOMY)
        elif sec == "S3":
            it["category"] = _categorize(it, _S3_TAXONOMY)


# A short bank name is a substring of longer institution names — a plain
# `"bank of india" in body` attached every Reserve Bank of India story to
# the Bank of India watchlist row. A match is rejected when the name is
# really the tail of one of these longer names, and when it sits inside a
# larger word.
_NAME_PREFIX_BLOCK_RE = re.compile(
    r"(?:\breserve|\bstate|\bcentral|\bunion|\bfederal|\bexim|"
    r"export[- ]import|\bworld|\bpunjab national)\s+$",
    re.IGNORECASE,
)


def _contains_name(body: str, phrase: str) -> bool:
    if not phrase:
        return False
    for m in re.finditer(re.escape(phrase), body):
        if m.start() and (body[m.start() - 1].isalnum()):
            continue
        if m.end() < len(body) and body[m.end()].isalnum():
            continue
        if _NAME_PREFIX_BLOCK_RE.search(body[:m.start()]):
            continue
        return True
    return False


# Some console aliases are short/generic enough to collide with unrelated
# usage: "MUDRA" is also the Hindi word for a hand gesture/currency, a yoga
# term, and the name of an unrelated ad agency ("Mudra Communications").
# A bare alias match on these needs nearby context confirming the story is
# actually about the India refinance agency/scheme, not just any use of
# the word -- same problem as the Red Fort/Delhi-monument collision fixed
# in fetch_news.py's short-name guard, but for console-entered aliases.
_AMBIGUOUS_ALIAS_CONTEXT = {
    "mudra": re.compile(
        r"\b(india|pmmy|pradhan mantri|refinanc|shishu|kishor(?:\W|$)|tarun|"
        r"micro units?|msme loan|small business loan|mudra loan|"
        # Co-mentioned Indian government credit/employment schemes: a
        # headline naming several of these alongside MUDRA (e.g. "KCC,
        # MUDRA, PMEGP, Vishwakarma, SVANidhi Loan") is unambiguously
        # about the scheme, not the unrelated word/agency, even with no
        # other context word present.
        r"pmegp|svanidhi|\bkcc\b|kisan credit card|vishwakarma|yojana|"
        r"loan scheme)\b", re.IGNORECASE),
}


def _alias_matches(body: str, alias: str) -> bool:
    if not _contains_name(body, alias.lower()):
        return False
    guard = _AMBIGUOUS_ALIAS_CONTEXT.get(alias.strip().lower())
    return bool(guard.search(body)) if guard else True


def _match_companies(it: dict, rows: list[dict]) -> list[str]:
    """Tag from the fetcher is authoritative (the item came from that
    company's own query); text phrase match is only a fallback. Re-matching
    by text alone silently dropped tagged items whose headline did not
    repeat the company name."""
    # "&" vs "and": a registered name says "Jammu & Kashmir Bank Limited"
    # but real press headlines almost always spell it "Jammu and Kashmir
    # Bank" -- a literal substring match on either form alone missed the
    # other. Normalising both sides to "and" makes the two forms equivalent
    # wherever they're compared as literal text.
    body = (it["title"] + " " + it["summary"]).lower().replace(" & ", " and ")
    tag = it.get("wl_company", "").lower()
    hits = []
    for r in rows:
        name = r["company"].strip()
        if not name:
            continue
        n = name.lower().replace(" & ", " and ")
        # Console aliases must be honoured HERE as well as at fetch time.
        # The two name checks are independently implemented, and whenever
        # they have disagreed the result was the worst possible one: the
        # story is fetched under the alias, then silently dropped here for
        # "never mentioning" the entity — real news lost with only a [WARN]
        # to show for it. A story that says only "BOI" or "HDFC Life" is
        # about that entity by the desk's own explicit instruction.
        aliases = [str(a).strip() for a in (r.get("aliases") or []) if str(a).strip()]
        alias_hit = any(_alias_matches(body, a) for a in aliases)
        tag_match = tag and (tag == n or tag.startswith(n) or n.startswith(tag))
        if tag_match and not alias_hit:
            # Sanity: the story must actually mention the company. Google's
            # per-company query sometimes returns unrelated stories (e.g. a
            # Patanjali deal from 'D. S. Integrated's query because 'd.' is
            # a substring of every 'Ltd.').
            if _sig_words(name) and not _mentions_company(body, name):
                print(f"[WARN] tag '{name[:40]}' but story never mentions it: "
                      f"'{it['title'][:60]}' — dropped from this company")
                tag_match = False
        if (tag_match or alias_hit
                or _contains_name(body, n) or _contains_name(body, _phrase(name))):
            hits.append(name)
    return hits


def _row_aliases(rows: list[dict]) -> dict:
    """{company: [alias, ...]} from the console's per-row Aliases column.
    Blank entries are dropped so an untouched column costs nothing."""
    out = {}
    for r in rows:
        name = (r.get("company") or "").strip()
        al = [str(a).strip() for a in (r.get("aliases") or []) if str(a).strip()]
        if name and al:
            out[name] = al
    return out


# ---------------------------------------------------------------------------
# Dedup memory (30-day, independent of the Claude report's memory)
# ---------------------------------------------------------------------------

def _key(it: dict) -> str:
    return f"{it['source']}: {it['title']}".lower().strip()[:120]


def _seen_fingerprint(it: dict) -> str:
    """Story identity that survives rewording and a change of outlet: the
    sorted distinctive tokens of the headline. Empty when the headline is
    too generic to fingerprint safely (fewer than 3 distinctive tokens),
    in which case only the exact key applies and nothing is over-dropped."""
    dist = sorted(_distinctive_toks(it.get("title", "")))
    # The FULL distinctive set, not a truncation. Taking the first N sorted
    # tokens dropped exactly the words that identify the story — "tata" and
    # "sons" sort last and fell off the end — so unrelated stories could
    # collide on their boilerplate remainder and a real item would be
    # silently suppressed. Requiring the whole set to match is stricter: it
    # catches rewording and re-ordering across outlets (which is the common
    # case) and declines to guess on heavier rewrites. Over-suppression
    # loses news; a surviving duplicate is merely untidy.
    return "|".join(dist) if len(dist) >= 3 else ""


def _is_already_sent(it: dict, seen: set) -> bool:
    """True when this exact item, or the same story under another headline
    or outlet, already went out on an earlier day."""
    if _key(it) in seen:
        return True
    fp = _seen_fingerprint(it)
    return bool(fp) and f"fp:{fp}" in seen


def _load_seen() -> set[str]:
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        today = str(datetime.date.today())
        keys: set[str] = set()
        for d, ks in data.get("days", {}).items():
            if d < today:
                keys.update(ks)
        return keys
    except Exception:
        return set()


def _save_seen(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(_SEEN_PATH), exist_ok=True)
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            days = json.load(f).get("days", {})
    except Exception:
        days = {}
    # Exact key PLUS a distinctive-token fingerprint. The exact key is
    # "{source}: {title}", so the same story reworded — or simply carried by
    # a different outlet tomorrow — produced a different key and came back
    # as "new" the next day. The fingerprint lets tomorrow's run recognise
    # it as already sent. Prefixed "fp:" so old files (plain keys only) stay
    # readable and the two never collide.
    days[str(datetime.date.today())] = (
        [_key(it) for it in items]
        + [f"fp:{fp}" for fp in {_seen_fingerprint(it) for it in items} if fp])
    cutoff = str(datetime.date.today() - datetime.timedelta(days=30))
    days = {d: v for d, v in days.items() if d >= cutoff}
    with open(_SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, indent=2)
    _git_push(_SEEN_PATH)


# ---------------------------------------------------------------------------
# Fetched-news pool
# ---------------------------------------------------------------------------
# Every run used to search Google live and keep only what that one search
# returned. Google serves a different subset each time — two runs ten minutes
# apart gave SIDBI 5 items and then 4 — so anything a run happened to miss was
# gone for good, and a throttled run could wipe an entity's coverage for the
# day. The pool makes coverage cumulative instead: each run merges what it
# fetched into a store, and the mail is built from everything collected in the
# retention window. Recency is still decided by the item's own PUB date via
# _is_stale; this window only governs how long a fetched line is remembered.
_POOL_PATH = os.path.join(_REPO_ROOT, "data", "news_pool.json")
# 96h, not 72: Saturday no longer runs at all, so an item pooled at Friday's
# ~07:35 IST run is exactly 72h old by Monday's ~07:35 IST run — right at
# the old cutoff, with no margin for the run's own timing slop. 96h keeps a
# Friday-morning item safely inside the window through Monday's send.
_POOL_HOURS = 96


def _pool_key(line: str) -> str:
    """Stable identity for a raw fetched line, ignoring the tier tag."""
    text = re.sub(r"^\[T\d\]", "", line.strip())
    return _norm_key(text)[:160]


def _load_pool() -> dict:
    try:
        with open(_POOL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", {}) or {}
    except Exception:
        return {}


def _merge_pool(fresh_lines: list[str]) -> tuple[list[str], dict, int]:
    """Fold this run's lines into the stored pool and drop anything past the
    retention window. Returns (all lines, pool to save, how many are new)."""
    pool = _load_pool()
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=_POOL_HOURS)
    kept: dict = {}
    for key, rec in pool.items():
        try:
            seen = datetime.datetime.fromisoformat(rec.get("first_seen", ""))
        except Exception:
            continue
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=datetime.timezone.utc)
        if seen >= cutoff and rec.get("line"):
            kept[key] = rec
    carried = len(kept)
    stamp = now.isoformat()
    for line in fresh_lines:
        key = _pool_key(line)
        if not key:
            continue
        if key not in kept:
            kept[key] = {"line": line, "first_seen": stamp}
    new = len(kept) - carried
    print(f"[pool] {len(fresh_lines)} fetched, {new} new, {carried} carried over "
          f"from the last {_POOL_HOURS}h -> {len(kept)} candidate items")
    return [rec["line"] for rec in kept.values()], kept, new


def _save_pool(pool: dict) -> None:
    os.makedirs(os.path.dirname(_POOL_PATH), exist_ok=True)
    with open(_POOL_PATH, "w", encoding="utf-8") as f:
        json.dump({"items": pool}, f, ensure_ascii=False)
    _git_push(_POOL_PATH)


def _git_push(path: str, content: str | None = None) -> None:
    """Publish a state file to main.

    Same convergent strategy as the 7:30 report's writer, and for the same
    reason: these are state files where the correct conflict resolution is
    "mine wins", never a merge. Rebase-and-retry cannot converge — a rebase
    of a conflicting change to the same generated file conflicts identically
    on every attempt. That is exactly how 7:30 sent its report four times in
    one morning while its marker sat unpublished since 07 Aug. This function
    guards team_last_sent.json, where the same failure would mean a
    duplicate mail to the whole team.

    content, when given, is re-written after each reset so every attempt
    reapplies our value on top of whatever is currently on main.
    """
    import subprocess
    import time as _time
    import random as _random

    # Local mode: run the whole pipeline and send the mail, but never touch
    # the git repo. This function does `git reset --mixed origin/main` and
    # pushes to main, which is right for a throwaway CI checkout and quite
    # wrong for someone's working copy on an office machine. State files are
    # still written to disk — they simply are not published.
    if os.environ.get("LOCAL_RUN", "").strip().lower() in ("1", "true", "yes"):
        print(f"[git] LOCAL_RUN — not publishing {os.path.basename(path)} to main")
        if content is not None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        return

    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            subprocess.run(["git", "remote", "set-url", "origin",
                            f"https://x-access-token:{token}@github.com/mjitendrafeb-cmd/jeetz.git"],
                           cwd=_REPO_ROOT, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
                       cwd=_REPO_ROOT, capture_output=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"],
                       cwd=_REPO_ROOT, capture_output=True)
    except Exception as exc:
        print(f"[git] setup failed (non-fatal): {exc}")
        return

    attempts = 8
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(["git", "fetch", "origin", "main"],
                           cwd=_REPO_ROOT, capture_output=True, timeout=60)
            subprocess.run(["git", "reset", "--mixed", "origin/main"],
                           cwd=_REPO_ROOT, capture_output=True)
            if content is not None:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            subprocess.run(["git", "add", path], cwd=_REPO_ROOT, capture_output=True)
            committed = subprocess.run(["git", "commit", "-m", "chore: update team news memory"],
                                       cwd=_REPO_ROOT, capture_output=True)
            if committed.returncode != 0:
                return  # already identical to main — nothing to publish
            push = subprocess.run(["git", "push", "origin", "HEAD:main"],
                                  cwd=_REPO_ROOT, capture_output=True, timeout=120)
            if push.returncode == 0:
                if attempt > 1:
                    print(f"[git] push succeeded on attempt {attempt}/{attempts} for {path}")
                return
            print(f"[git] push attempt {attempt}/{attempts} rejected for {path} "
                  f"({push.stderr.decode(errors='replace').strip()[:160]})")
        except Exception as exc:
            print(f"[git] push attempt {attempt}/{attempts} errored for {path}: {exc}")
        _time.sleep(2 * attempt + _random.uniform(0, 2))
    print(f"[git] PUSH FAILED after {attempts} attempts: {path} "
          f"— duplicate-send guard is NOT protected for this run")


# ---------------------------------------------------------------------------
# HTML rendering (plain, no AI) -- table-based layout for email-client
# compatibility (Outlook/Gmail), cream/navy palette.
# ---------------------------------------------------------------------------

# Newspaper palette, matched to the reference design: white ground, deep
# navy chrome, teal used ONLY as an accent (active tab underline, section
# rule, dates, links). Red is retained for CONFIDENTIAL and for downgrade
# badges — both are alerts, not decoration, and the reference keeps
# CONFIDENTIAL red too.
_NP_NAVY = "#0E2E4E"
_NP_NAVY_DEEP = "#0A2440"
_NP_TEAL = "#1FBFC7"
_NP_TEAL_DK = "#0E8F9A"
_NP_INK = "#12283C"
_NP_BODY = "#41535F"
_NP_MUTED = "#8896A2"
_NP_RULE = "#E3E8EC"
# S1 entity-header band: a pale navy fill (chosen over three alternatives —
# a teal-coloured heading and a left accent bar — for the S1 entity header)
# so the header reads as a labelled block rather than another line of text,
# with no size or weight change from the surrounding cards.
_NP_HEADER_TINT = "#EEF3F8"
_NP_HEADER_TINT_RULE = "#B9C6D3"

_NAVY = "#132A46"
_NAVY_SOFT = "#9AA9BC"
_CREAM = "#EDEAE3"
_RED = "#A32638"
_GREEN = "#2E6B4F"
_GREY = "#8A8578"
_DIVIDER = "#ECE8E0"
_MANAGE_URL = "https://mjitendrafeb-cmd.github.io/jeetz/team.html"
# Daily run-status summary recipient. Sent once per real (non-test) run,
# after all team mails go out, so someone has a record of the run without
# opening GitHub Actions.
_STATUS_EMAIL = "careedgedailynews@gmail.com"

# Matches "up ~34%", "profit up 36%", "falls 12.5%", "-74.4%", "surges 8%"
_DELTA_RE = re.compile(
    r"\b(up|rise[sd]?|surge[sd]?|jump[sd]?|grow[sn]?|gain[sed]*|higher)\b[^%\d]{0,25}(\d+\.?\d*)\s*%"
    r"|(\d+\.?\d*)\s*%[^%]{0,15}\b(up|rise[sd]?|surge[sd]?|jump[sd]?|grow[sn]?|gain[sed]*|higher)\b"
    r"|\b(down|falls?|fell|declin\w*|drop[sped]*|slid\w*|contract\w*|lower)\b[^%\d]{0,25}(\d+\.?\d*)\s*%"
    r"|(\d+\.?\d*)\s*%[^%]{0,15}\b(down|falls?|fell|declin\w*|drop[sped]*|slid\w*|contract\w*|lower)\b",
    re.IGNORECASE,
)
_NEG_WORDS = ("down", "fall", "fell", "declin", "drop", "slid", "contract", "lower")


def _delta_badge(text: str) -> str:
    """Extract an 'up 36%' / 'down 74.4%' pattern and render a coloured
    up/down arrow badge, or '' if the item carries no percentage move."""
    m = _DELTA_RE.search(text)
    if not m:
        return ""
    groups = [g for g in m.groups() if g]
    pct = next((g for g in groups if re.match(r"^\d+\.?\d*$", g)), None)
    if not pct:
        return ""
    negative = any(w in m.group(0).lower() for w in _NEG_WORDS)
    color = _RED if negative else _GREEN
    arrow = "&#9660;" if negative else "&#9650;"
    sign = "-" if negative else "+"
    return (f' &middot; <span style="color:{color};font-weight:bold">'
            f'{arrow} {sign}{pct}%</span>')


def _item_polarity(it: dict) -> str:
    text = f'{it["title"]} {it["summary"]}'
    m = _DELTA_RE.search(text)
    if not m:
        return "neutral"
    return "negative" if any(w in m.group(0).lower() for w in _NEG_WORDS) else "positive"


def _item_html(it: dict) -> str:
    meta = " &middot; ".join(x for x in (it["source"], it["pub"]) if x)
    delta = _delta_badge(f'{it["title"]} {it["summary"]}')
    meta_html = f'{meta}{delta}' if (meta or delta) else ""
    style = (f"font-family:Georgia,'Times New Roman',serif;font-size:15px;"
             f"line-height:21px;color:{_NAVY};font-weight:bold;text-decoration:none")
    # 7:30 LINKS rule: if an item has no URL, render it without any link —
    # never emit href="#" (that produced dead headlines in S5).
    headline = (f'<a href="{it["url"]}" style="{style}">{it["title"]}</a>'
                if it["url"] else f'<span style="{style}">{it["title"]}</span>')
    return f"""<tr><td style="padding:10px 0;border-bottom:1px solid {_DIVIDER}">
{headline}
<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:{_GREY};margin-top:3px">{meta_html}</div>
</td></tr>"""


def _sec_banner(title: str, color: str = _RED) -> str:
    """Section header -- full-width dark bar with a coloured accent edge."""
    return f"""<tr><td style="padding:22px 0 0 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background:{_NAVY};color:#fff;font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;padding:7px 12px;border-left:4px solid {color}">{title}</td>
</tr></table></td></tr>"""


def _company_banner(name: str, items: list = None) -> str:
    """Company sub-header -- small caps label with a coloured left border.
    Green only when every dated move for this company is a positive
    percentage move; red (brand default) otherwise."""
    polarities = [_item_polarity(it) for it in (items or [])]
    color = _GREEN if polarities and all(p == "positive" for p in polarities) and \
        any(p != "neutral" for p in polarities) else _RED
    return f"""<tr><td style="padding:18px 0 0 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="border-left:3px solid {color};padding-left:12px;font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:{color};font-weight:bold">{name}</td>
</tr></table></td></tr>"""


def _shell(recipient_name: str, date_str: str, company_count: int, story_count: int,
           inner_rows: str, preheader: str) -> str:
    plural_c = "y" if company_count == 1 else "ies"
    if story_count:
        subtitle = (f"{company_count} compan{plural_c} &nbsp;&middot;&nbsp; "
                    f"{story_count} stor{'y' if story_count == 1 else 'ies'} today")
    else:
        subtitle = f"{company_count} compan{plural_c} &nbsp;&middot;&nbsp; no new stories today"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<style>
  body {{ margin:0; padding:0; background-color:{_CREAM}; }}
  table {{ border-collapse:collapse; }}
  a {{ text-decoration:none; }}
  @media (max-width:620px) {{
    .container {{ width:100% !important; }}
    .stack-pad {{ padding-left:20px !important; padding-right:20px !important; }}
  }}
</style></head>
<body style="margin:0;padding:0;background-color:{_CREAM};font-family:Georgia,'Times New Roman',serif">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:{_CREAM}">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td align="center" style="padding:32px 16px">
<table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background-color:#FFFFFF">

<tr><td style="background-color:{_NAVY};padding:28px 32px" class="stack-pad">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="font-family:Arial,Helvetica,sans-serif;color:{_CREAM};font-size:12px;letter-spacing:2px;text-transform:uppercase">Daily News</td>
<td align="right" style="font-family:Arial,Helvetica,sans-serif;color:{_NAVY_SOFT};font-size:12px">{date_str}</td>
</tr></table>
<div style="font-family:Georgia,'Times New Roman',serif;color:#FFFFFF;font-size:26px;line-height:32px;font-weight:bold;margin-top:14px">CareEdge Daily News</div>
<div style="font-family:Arial,Helvetica,sans-serif;color:{_CREAM};font-size:14px;margin-top:4px">For {recipient_name}</div>
<div style="font-family:Arial,Helvetica,sans-serif;color:{_NAVY_SOFT};font-size:13px;margin-top:6px">{subtitle}</div>
</td></tr>

<tr><td style="padding:28px 32px 8px 32px" class="stack-pad">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
{inner_rows}
</table>
</td></tr>

<tr><td align="center" style="padding:28px 32px 8px 32px" class="stack-pad">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td bgcolor="{_NAVY}" style="border-radius:4px">
<a href="{_MANAGE_URL}" style="display:block;padding:12px 28px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#FFFFFF;font-weight:bold;letter-spacing:0.5px">Manage Watchlist &amp; Recipients</a>
</td></tr></table>
</td></tr>

<tr><td style="padding:24px 32px 32px 32px;border-top:1px solid {_DIVIDER}" class="stack-pad">
<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:{_GREY};line-height:18px">
Auto-generated for your watchlist &middot; <a href="{_MANAGE_URL}" style="color:{_NAVY};text-decoration:underline">Manage companies &amp; recipients</a>
</div>
<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#B0AA9C;line-height:16px;margin-top:14px">
CareEdge Daily News &mdash; internal digest. Sources are aggregated from public RSS/news feeds; no AI analysis is applied to this mail.
</div>
</td></tr>

</table>
</td></tr></table>
</body></html>"""

# ---------------------------------------------------------------------------
# Newspaper-format rendering — mirrors the 7:30 report's layout exactly by
# reusing send_credit_report's build_attachment/build_email (lazily imported
# to avoid a circular import), with per-person S1 and section subscriptions.
# No AI: cards carry headline+summary; the AI's credit-implication sentence
# and cross-source dedup are the only pieces that need API credits.
# ---------------------------------------------------------------------------

_NP_SECTIONS = [
    ("s1", "sb1", "S1", "&#9733; S1 &mdash; MY RATED ENTITIES &amp; WATCHLIST"),
    ("s2", "sb2", "S2", "S2 &mdash; SECTOR &amp; REGULATION"),
    ("s3", "sb3", "S3", "S3 &mdash; MACROECONOMIC &amp; MARKETS"),
]

_NP_PAGES = [
    ("s1", "&#9733; My Rated Entities &amp; Watchlist", "1"),
    ("s2", "Sector &amp; Regulation", "2"),
    ("s3", "Macroeconomic &amp; Markets", "3"),
]

_RATING_ACTION_RE = re.compile(
    r"\b(upgrad\w*|downgrad\w*|rating watch|outlook (revised|negative|positive)|"
    r"revises? outlook|defaults?\b|delays? (in )?(payment|repayment)|withdraws? rating)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# (B)+(G) Event taxonomy and materiality
# ---------------------------------------------------------------------------
# Previously every surviving item was weighted the same and ordered by fetch
# order, so a branch opening sat above a downgrade. A credit desk needs
# prioritisation, not just filtration. Each item is classified into an event
# type; the type carries a materiality score that drives S1/S2-S5 ordering,
# the Top-5 selection, and whether an item earns a full card at all.
_EVENTS = [
    # (key, label, score, colour, regex)
    ("DEFAULT", "DEFAULT", 10, "#b91c1c", re.compile(
        r"\b(defaults?\b|defaulted|payment delay|delays? in (payment|repayment|servicing)|"
        r"missed (payment|interest|coupon)|invocation of (pledge|guarantee)|"
        r"insolvency|\bcirp\b|nclt admits?|liquidation|wilful defaulter|"
        r"\bsma-?[012]\b|debt restructur)", re.IGNORECASE)),
    ("RATING", "RATING", 9, "#15803d", re.compile(
        r"\b(upgrad\w*|downgrad\w*|rating watch|credit watch|placed on watch|"
        r"outlook (revised|negative|positive|stable)|revises? outlook|"
        r"reaffirm\w*|withdraws? rating|assigns? (?:\d\.\d|[^.|]){0,25}rating)", re.IGNORECASE)),
    ("REGULATORY", "REGULATORY", 8, "#b45309", re.compile(
        r"\b(monetary penalty|imposes? (a )?penalt|penalis|penaliz|enforcement action|"
        r"adjudication order|show cause notice|debarr|cease and desist|sebi order|"
        r"compounding order|licence (cancel|revok)|registration cancel)", re.IGNORECASE)),
    ("MANAGEMENT", "MANAGEMENT", 7, "#7c3aed", re.compile(
        r"\b((ceo|cfo|md|managing director|chairman|auditor|director)(?:\d\.\d|[^.|]){0,30}"
        r"(resign|steps? down|quits?|exits?|appoint|elevat)|"
        r"(resign|steps? down|quits?)(?:\d\.\d|[^.|]){0,25}(ceo|cfo|md|chairman|auditor)|"
        r"auditor (resign|change)|board (approves|appoints))", re.IGNORECASE)),
    ("FUNDING", "FUNDING", 6, "#1e3a8a", re.compile(
        r"\b(raises?\s+(rs\.?\s?)?[\d.,]+\s*(crore|cr\b|million|billion)|"
        r"fund ?rais\w*|funding round|series [a-f]\b|\bqip\b|rights issue|"
        r"preferential allotment|capital infusion|tier[- ]?(i|ii|1|2) bonds?|"
        r"issues? (ncds?|debentures?|bonds?)|capital raise|"
        r"allots?(?:\d\.\d|[^.|]){0,25}\b(commercial paper|ncds?|debentures?|bonds?)\b)",
        re.IGNORECASE)),
    ("M&A", "M&amp;A", 6, "#0f766e", re.compile(
        r"\b(acqui(re|res|red|sition)|merger|amalgamat\w*|stake (sale|buy|purchase|acquisition)|"
        r"divest\w*|takeover|open offer|slump sale)", re.IGNORECASE)),
    ("RESULTS", "RESULTS", 4, "#525252", re.compile(
        r"\b(q[1-4]\s?(fy)?\d*|quarterly|net profit|\bpat\b|\bnii\b|"
        r"net interest income|earnings|results?\b|gross npa|net npa)", re.IGNORECASE)),
]

# S2/S3 items are sector/macro stories, not tied to one watchlist entity, so
# _EVENTS above never fires for them: it always misses the +2 "companies"
# bonus _materiality() gives S1 rows, and its patterns are written for
# entity-specific corporate actions ("downgrades X's rating", "SEBI order
# against Y") -- a genuinely major sector/macro headline ("RBI flags
# systemic cyber risk at UCBs", "MPC holds repo rate") never matches any of
# them and silently scores OTHER=1, so S2/S3 could never turn red no matter
# how material the story actually was. This is a parallel, S2/S3-scoped
# table so real significance there can surface the same way it does in S1.
_S2S3_EVENTS = [
    # (key, label, score, colour, regex)
    ("SOVEREIGN", "SOVEREIGN RATING", 9, "#b91c1c", re.compile(
        r"\b(moody'?s|s&p|fitch|crisil|icra)\b.{0,40}\b(upgrades?|downgrades?|"
        r"affirms?|revises? outlook)\b.{0,30}\bindia\b|india'?s sovereign rating|"
        r"sovereign (rating|outlook)", re.IGNORECASE)),
    ("SYSTEMIC_RISK", "SYSTEMIC RISK", 9, "#b91c1c", re.compile(
        r"\b(systemic risk|financial stability risk|contagion risk|bank run|"
        r"crisis in the (nbfc|banking|microfinance|co-?operative) sector|"
        r"sector-wide (risk|stress|vulnerabilit))\b", re.IGNORECASE)),
    # A named regulator's own top official (not just the regulator generically)
    # flagging risk/vulnerability is a real signal even without one of the
    # SYSTEMIC_RISK phrases above -- e.g. "Small UCBs face risks bigger than
    # their size due to cyber threats: RBI Dy Governor" mentions neither
    # "systemic" nor "sector-wide" but is exactly this category. Two
    # lookaheads instead of a fixed order, since the headline can name the
    # official before or after (often after, as an attribution) the actual
    # warning content.
    ("REGULATOR_WARNING", "REGULATOR WARNING", 8, "#b45309", re.compile(
        r"(?=.*\b(rbi|sebi|irdai|pfrda)\b.{0,20}\b(governor|deputy governor|"
        r"chairman|chairperson|whole[- ]time member)\b)"
        r"(?=.*\b(risks?|vulnerab\w*|warns?|flags?|cautions?|threats?)\b)",
        re.IGNORECASE)),
    ("POLICY_ACTION", "REGULATORY ACTION", 8, "#b45309", re.compile(
        r"\b(rbi|sebi|irdai|pfrda)\b.{0,50}\b(bars?|bans?|revokes?|cancels?|"
        r"imposes? (a )?(monetary )?penalt|enforcement action|show cause notice|"
        r"debarr|cease and desist|compounding order)\b", re.IGNORECASE)),
    ("RATE_DECISION", "RATE DECISION", 8, "#1e3a8a", re.compile(
        r"\b(mpc|monetary policy committee)\b.{0,40}\b(cuts?|hikes?|raises?|"
        r"holds?|keeps? unchanged|leaves? unchanged)\b|"
        r"repo rate (cut|hike|unchanged|raised|lowered|held)", re.IGNORECASE)),
    ("MARKET_SHOCK", "MARKET SHOCK", 7, "#7c3aed", re.compile(
        r"\b(rupee (plunges?|crashes?|hits? (a )?record low)|"
        r"sensex (crashes?|plunges?|tanks?)|bond yields? (spike|surge)|"
        r"market (crash|meltdown|sell-?off))\b", re.IGNORECASE)),
]


def _event_of(it: dict) -> tuple[str, str, int, str]:
    """(key, label, score, colour). Highest-materiality match wins.
    S2/S3 items use their own event table -- see _S2S3_EVENTS."""
    text = f'{it.get("title","")} {it.get("summary","")}'
    table = _S2S3_EVENTS if it.get("section") in ("S2", "S3") else _EVENTS
    for key, label, score, colour, rx in table:
        if rx.search(text):
            return key, label, score, colour
    return "OTHER", "", 1, "#9ca3af"


def _materiality(it: dict) -> int:
    """Event score plus context: a watchlist name and a primary source both
    raise how much the item deserves the reader's attention."""
    _, _, score, _ = _event_of(it)
    if it.get("companies"):
        score += 2
    if "T1" in (it.get("tags") or ""):
        score += 1
    return score


# (D) Recency: rating-agency press pages and the custom scraper carry no
# date, and the 7:30 prompt warns those "often surface months-old actions".
# Undated items are kept — a CRISIL action matters even undated — but they
# never lead a section, and they say so on the card.
def _is_undated(it: dict) -> bool:
    return not (it.get("pub") or "").strip()


_ARCHIVE_URL = "https://mjitendrafeb-cmd.github.io/jeetz/archive/"

# Google News RSS returns encoded redirect links
# (news.google.com/rss/articles/CBMi...?oc=5). Those are NOT openable article
# URLs — pasted into a browser they 404 or bounce, which is why every S1
# "Read more" was dead. Resolve each one to the publisher's real URL; if that
# fails, fall back to a Google News *search* link for the headline, which
# always opens even though it costs the reader one extra click.
_GNEWS_ARTICLE_RE = re.compile(r"^https?://news\.google\.com/rss/articles/", re.IGNORECASE)
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_GOOGLE_HOST_RE = re.compile(r"^https?://(news\.|www\.|accounts\.|policies\.|support\.)?google\.", re.IGNORECASE)
# Google's article page links the publisher's FAVICON before the article, on
# googleusercontent.com — which is not a "google.com" host, so the old
# fallback returned it and 36 of one edition's 40 "Read more" links pointed at
# a 16px image (including a CRISIL rating-action story). Asset hosts and
# image/sizing URLs must be rejected explicitly.
_ASSET_HOST_RE = re.compile(
    r"^https?://[^/]*\b(googleusercontent|gstatic|ggpht|googleapis|"
    r"googletagmanager|doubleclick)\.com", re.IGNORECASE)
_ASSET_PATH_RE = re.compile(
    r"\.(jpe?g|png|gif|webp|svg|ico|css|js|woff2?)(\?|$)"
    r"|[=/][ws]\d{2,4}(-[a-z0-9-]*)?$", re.IGNORECASE)


def _is_article_url(u: str) -> bool:
    """A real article link — not a Google page, an asset host, or an image."""
    if not u or _GOOGLE_HOST_RE.match(u) or _ASSET_HOST_RE.match(u):
        return False
    return not _ASSET_PATH_RE.search(u)


def _gnews_search_url(title: str) -> str:
    import urllib.parse
    q = urllib.parse.quote((title or "")[:120])
    return f"https://news.google.com/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


_PRINTABLE_URL_RE = re.compile(r'^[\x21-\x7e]+$')


def _decode_gnews_id(url: str) -> str:
    """Publisher URL decoded straight out of the Google News article id.

    Google serves the redirect page via JavaScript now, so fetching it
    resolves nothing (an edition logged 0/24 resolved, and every reader got
    a search link instead of the article). The common 'CBMi...' id is
    base64url of a protobuf blob that carries the publisher URL as a
    length-prefixed string, so it can be read offline with no request at
    all. Returns "" when the id is a format this cannot read, and the
    caller falls through to the network attempt exactly as before.
    """
    m = _GNEWS_ARTICLE_RE.match(url or "")
    if not m:
        return ""
    seg = url[m.end():].split("?")[0].split("/")[0]
    if len(seg) < 16:
        return ""
    import base64
    for pad in range(4):
        try:
            raw = base64.urlsafe_b64decode(seg + "=" * pad)
        except Exception:
            continue
        hit = re.search(rb'https?://', raw)
        if not hit:
            continue
        start = hit.start()
        if start == 0:
            break
        # The varint length sits immediately before the string; using it
        # stops the next protobuf field's bytes leaking onto the URL.
        i = start - 1
        vb = [raw[i]]
        while i - 1 >= 0 and raw[i - 1] & 0x80:
            i -= 1
            vb.insert(0, raw[i])
        n = sum((b & 0x7f) << (7 * k) for k, b in enumerate(vb))
        cand = ""
        if 10 <= n <= len(raw) - start:
            cand = raw[start:start + n].decode("utf-8", "ignore")
        if not (cand and _PRINTABLE_URL_RE.match(cand)):
            cand = re.split(rb'[^\x21-\x7e]', raw[start:])[0].decode("utf-8", "ignore")
        return cand if cand and _is_article_url(cand) else ""
    return ""


_BATCH_ENDPOINT = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def _resolve_via_batchexecute(url: str) -> str:
    """Ask Google itself to translate the article id into the publisher URL.

    Newer article ids are opaque — the publisher URL is no longer embedded
    in the base64, which is why the offline decoder resolved 0 of 33 links
    in a live run. Google's own splash endpoint still translates them: the
    article page carries a signature and timestamp, and posting those back
    returns the real URL. Any failure returns "" so the caller falls
    through to the existing fallbacks and links are never worse than now.
    """
    m = _GNEWS_ARTICLE_RE.match(url or "")
    if not m:
        return ""
    art_id = url[m.end():].split("?")[0].split("/")[0]
    if not art_id:
        return ""
    try:
        import requests
        page = requests.get(f"https://news.google.com/rss/articles/{art_id}",
                            headers={"User-Agent": _BROWSER_UA}, timeout=10)
        body = page.text or ""
        sg = re.search(r'data-n-a-sg="([^"]+)"', body)
        ts = re.search(r'data-n-a-ts="([^"]+)"', body)
        if not (sg and ts):
            return ""
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            art_id, int(ts.group(1)), sg.group(1),
        ], separators=(",", ":"))
        freq = json.dumps([[["Fbv4je", inner, None, "generic"]]],
                          separators=(",", ":"))
        resp = requests.post(
            _BATCH_ENDPOINT, data={"f.req": freq}, timeout=10,
            headers={"User-Agent": _BROWSER_UA,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        text = resp.text or ""
        # Response is ")]}'" then JSON lines; the payload holds ["garturlres","<url>"]
        hit = re.search(r'\[\\"garturlres\\",\\"(https?://[^\\"]+)', text)
        if not hit:
            hit = re.search(r'"garturlres","(https?://[^"]+)"', text)
        if hit:
            cand = hit.group(1).replace("\\/", "/").replace("\\u003d", "=") \
                               .replace("\\u0026", "&")
            return cand if _is_article_url(cand) else ""
    except Exception as exc:
        print(f"[links] batchexecute failed ({exc.__class__.__name__}) for {art_id[:28]}...")
    return ""


def _resolve_gnews_url(url: str, title: str) -> str:
    """Return the publisher's article URL, or a Google News search link."""
    decoded = _decode_gnews_id(url)
    if decoded:
        return decoded
    decoded = _resolve_via_batchexecute(url)
    if decoded:
        return decoded
    try:
        import requests
        r = requests.get(url, timeout=8, allow_redirects=True,
                         headers={"User-Agent": _BROWSER_UA})
        final = r.url or ""
        if _is_article_url(final):
            return final
        body = r.text or ""
        m = re.search(r'data-n-au="(https?://[^"]+)"', body)
        if m and _is_article_url(_html.unescape(m.group(1))):
            return _html.unescape(m.group(1))
        for m in re.finditer(r'href="(https?://[^"]+)"', body):
            cand = _html.unescape(m.group(1))
            if _is_article_url(cand):
                return cand
    except Exception as exc:
        print(f"[links] resolve failed ({exc.__class__.__name__}) for {url[:60]}...")
    # Last resort: hand back Google's own redirect rather than a search
    # page. A real browser follows it to the article, whereas the search
    # link always cost the reader a click and an extra guess.
    return url if _GNEWS_ARTICLE_RE.match(url or "") else _gnews_search_url(title)


def _resolve_gnews_links(items: list[dict]) -> None:
    """Rewrite every Google News redirect URL in place, concurrently."""
    title_by_url: dict[str, str] = {}
    for it in items:
        u = it.get("url", "")
        if u and _GNEWS_ARTICLE_RE.match(u) and u not in title_by_url:
            title_by_url[u] = it.get("title", "")
    if not title_by_url:
        return
    import concurrent.futures
    resolved: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_resolve_gnews_url, u, t): u
                   for u, t in title_by_url.items()}
        for fut in concurrent.futures.as_completed(futures):
            u = futures[fut]
            try:
                resolved[u] = fut.result()
            except Exception:
                resolved[u] = _gnews_search_url(title_by_url[u])
    for it in items:
        if it.get("url") in resolved:
            it["url"] = resolved[it["url"]]
    direct = sum(1 for v in resolved.values() if _is_article_url(v))
    print(f"[links] {direct}/{len(resolved)} Google News links resolved to the "
          f"publisher's page ({len(resolved) - direct} fell back to a search link)")


def _parse_pub(pub: str, today: "datetime.date"):
    """PUB dates arrive as '29 Jul' (no year). Assume current year; a date
    that lands in the future means it was last year (year boundary)."""
    try:
        d = datetime.datetime.strptime(pub.strip(), "%d %b").date().replace(year=today.year)
        if d > today + datetime.timedelta(days=1):
            d = d.replace(year=today.year - 1)
        return d
    except Exception:
        return None


def _is_stale(it: dict, today: "datetime.date", max_age_days: int = 2) -> bool:
    """7:30 recency rule, mechanical version: drop items whose PUB date shows
    the story is older than 48h. Undated items are kept (conservative)."""
    d = _parse_pub(it.get("pub", ""), today)
    return d is not None and (today - d).days > max_age_days


# Event-DATE freshness, not just search-result date: a macro-data article
# can be freshly CRAWLED today while describing an old reference period —
# a January CPI writeup resurfacing in an August search still says "January
# CPI", it just wasn't indexed until now. _is_stale above only catches the
# crawl date; this catches the DATA date. Scoped narrowly to the handful of
# stats that are always described by name-of-period (CPI/WPI/IIP/GDP/PMI) —
# a story that merely mentions a past month in passing ("since January") but
# is not itself a dated data release is left alone.
_MACRO_STAT_RE = re.compile(r"\b(cpi|inflation|wpi|iip|\bgdp\b|\bgva\b|\bpmi\b)\b", re.IGNORECASE)
_MONTH_MENTION_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[\s.]*(20\d{2})?\b", re.IGNORECASE)
_MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
              "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}


def _is_stale_macro_period(it: dict, today: "datetime.date") -> bool:
    """True when a CPI/WPI/IIP/GDP/PMI story explicitly names a reference
    month more than 3 calendar months old. Any ambiguity (no month found, no
    stat keyword, ""since January"" with no stat context) keeps the item —
    a missed stale item is cheap, a wrongly dropped live release is not.

    The month must sit near the stat keyword (same short window), not just
    anywhere in the text — "RBI holds rates, citing the inflation
    trajectory since January" mentions both words but is not itself a
    January-inflation data release; a document-wide search would wrongly
    flag it."""
    text = f'{it.get("title","")} {it.get("summary","")}'
    stat_hit = _MACRO_STAT_RE.search(text)
    if not stat_hit:
        return False
    window = text[max(0, stat_hit.start() - 45):stat_hit.end() + 45]
    m = _MONTH_MENTION_RE.search(window)
    if not m:
        return False
    month = _MONTH_NUM.get(m.group(1).lower()[:3])
    if not month:
        return False
    year = int(m.group(2)) if m.group(2) else today.year
    ref = datetime.date(year, month, 1)
    if ref > today:
        return False  # a forward-looking mention ("July print due in August"), not stale data
    age_months = (today.year - ref.year) * 12 + (today.month - ref.month)
    # India's monthly stats (CPI/IIP/WPI) normally release with a ~5-6 week
    # lag, so "2 months old" is already the outer edge of a genuinely fresh
    # release; a real 11 Aug case was "retail inflation rises to 3.93% in
    # May" resurfacing in August — 3 months old, and not remotely current.
    return age_months > 2


_TITLE_STOP = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "at",
               "as", "by", "with", "its", "is", "are", "from", "amid", "after"}


def _title_toks(title: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", title.lower())
                     if w not in _TITLE_STOP and len(w) > 2)


def _lead_tok(title: str) -> str:
    """First significant word — the story's subject. Two headlines about
    different issuers must never merge, however much boilerplate they share."""
    for w in re.findall(r"[a-z0-9]+", (title or "").lower()):
        if w not in _TITLE_STOP and len(w) > 2:
            return w
    return ""


def _tier_rank(it: dict) -> int:
    tags = it.get("tags", "")
    return 0 if "T1" in tags else (1 if "T2" in tags else 2)


# Boilerplate that appears in every other BFSI headline. A token here says
# nothing about WHICH story this is, so two headlines agreeing on these
# alone are not the same story ("HDFC Bank reports Q1 profit rise" vs
# "ICICI Bank reports Q1 profit rise" agree on almost everything except
# the one word that matters). Regulator names are deliberately NOT here —
# for a macro story "rbi"/"sebi" IS the subject.
_GENERIC_NEWS_WORD = frozenset("""
report reports reported says said announces announced announcement posts
post sees see expects expect plans plan gets get receives receive shows
show new news update updates
profit loss revenue income growth grow rise rises rising fall falls
falling gain gains decline declines drop drops jump jumps surge
crore lakh million billion percent pct rupee rupees
quarter quarterly q1 q2 q3 q4 fy year yearly annual month monthly
result results earnings margin margins yield yields rate rates
bank banks banking finance financial financing company companies limited
ltd firm firms group india indian sector sectors market markets business
strong weak higher lower total net gross
loan loans lending credit fund funds capital investment investments
share shares stock stocks price prices
""".split())


def _distinctive_toks(title: str) -> frozenset:
    """Title tokens that actually identify WHICH story this is."""
    return frozenset(t for t in _title_toks(title) if t not in _GENERIC_NEWS_WORD)


def _entity_key(it: dict) -> str:
    """Which watchlist entity this item belongs to, or "" if none."""
    comps = it.get("companies") or []
    if comps:
        return sorted(comps)[0].lower()
    return (it.get("wl_company") or "").strip().lower()


# Themes that a company produces ONCE per event, so every outlet's version
# is the same story. Deliberately broader than the _EVENTS taxonomy, which
# splits these across RESULTS/OTHER depending on exact wording — "logs Rs
# 62 crore profit" and "June-Quarter PAT 624.1 Million" describe one result
# but land in different event buckets.
_STORY_THEMES = (
    ("results", re.compile(
        r"\b(q[1-4]\b|quarter|quarterly|profit|profitable|\bpat\b|earnings|"
        r"results?\b|revenue|net income|\bnpa\b|asset quality|provisions?|"
        r"disbursement|\bpbt\b|bottom ?line)\b", re.IGNORECASE)),
    # Deliberately its own pattern, not _RATING_ACTION_RE: that one also
    # drives the card badges and the materiality score, so widening it
    # would change ordering and styling as a side effect. Here it only has
    # to recognise "this is the rating story" in whatever words an outlet
    # chose ("upgrades", "rating raised", "cuts rating to").
    ("rating", re.compile(
        r"\b(upgrad\w*|downgrad\w*|rating watch|credit watch|placed on watch|"
        r"outlook (revised|negative|positive|stable)|revises? outlook|"
        r"reaffirm\w*|withdraws? rating|assigns? (?:\d\.\d|[^.|]){0,25}rating|"
        r"rating (raised|cut|lowered|revised|upgraded|downgraded|reaffirmed)|"
        r"(raises|cuts|lowers|revises) (?:\d\.\d|[^.|]){0,20}rating)\b", re.IGNORECASE)),
)


def _story_theme(it: dict) -> str:
    text = f'{it.get("title","")} {it.get("summary","")}'
    for name, rx in _STORY_THEMES:
        if rx.search(text):
            return name
    return ""


def _dedup_cross_source(items: list[dict]) -> list[dict]:
    """7:30 rule, mechanical version: same story from several sources keeps
    ONE card (highest tier wins) with 'Also reported by: ...' under it.
    Watchlist items tagged to different companies are never merged.

    Matching is rarity-weighted rather than flat token overlap. The old rule
    (>=5 shared tokens AND >=0.55 plain ratio AND identical first word)
    failed on real reported duplicates: three versions of the Tata Sons
    upper-layer-NBFC story shared exactly the tokens that identify it
    (tata/sons/upper/layer/nbfc) yet scored 0.50 on flat ratio and had
    different lead words ('tata' vs 'india'), so all three shipped as
    separate cards. Weighting by rarity fixes that without merging
    'HDFC Bank Q1 profit' into 'ICICI Bank Q1 profit' — those two share
    only COMMON tokens, which now carry almost no weight.
    """
    kept: list[dict] = []
    for it in items:
        toks = _title_toks(it["title"])
        dist = _distinctive_toks(it["title"])
        lead = _lead_tok(it["title"])
        nkey = _norm_key(it["title"])
        it["also"] = it.get("also", [])
        winner = None
        for k in kept:
            a, b = it.get("wl_company", ""), k.get("wl_company", "")
            if a and b and a != b:
                continue  # same headline, different watchlist company — keep both
            if nkey and nkey == k["_nkey"]:
                winner = k          # byte-identical headline, always one card
                break
            if len(toks) < 4 or len(k["_toks"]) < 4:
                continue
            # Path 0: the same company's own recurring story, told by
            # several outlets in words that share almost nothing. Eight
            # versions of Fusion Finance's Q1 result all shipped as
            # separate cards because they agreed only on "fusion" — every
            # other shared word (profit, crore, quarter) is boilerplate
            # this file deliberately treats as meaningless. A company
            # reports a given quarter once, so same entity + same theme is
            # one story. Requires a confirmed entity match, so this can
            # never merge two different issuers.
            ent_a, ent_b = _entity_key(it), _entity_key(k)
            if ent_a and ent_a == ent_b:
                theme_a, theme_b = _story_theme(it), _story_theme(k)
                if theme_a and theme_a == theme_b:
                    winner = k
                    break
            # Path 1: three or more DISTINCTIVE tokens in common.
            # This is what catches a reworded duplicate whichever word the
            # outlet led with — the reported Tata Sons upper-layer-NBFC
            # trio shares tata/sons/upper/layer/nbfc and now collapses to
            # one card, while HDFC-vs-ICICI shares only boilerplate and
            # stays two.
            if len(dist & k["_dist"]) >= 3:
                winner = k
                break
            # Path 2 (original rule, unchanged): plenty of shared words AND
            # the same leading subject. Kept so nothing that merged before
            # stops merging now.
            inter = len(toks & k["_toks"])
            if inter < 5:
                continue
            if inter / min(len(toks), len(k["_toks"])) < 0.55:
                continue
            if lead and k["_lead"] and lead != k["_lead"]:
                continue
            winner = k
            break
        if winner is None:
            it["_toks"], it["_lead"], it["_nkey"], it["_dist"] = toks, lead, nkey, dist
            kept.append(it)
        elif _tier_rank(it) < _tier_rank(winner):
            # newcomer is higher-tier: it replaces the kept item in place
            it["also"] = winner["also"] + [winner["source"]]
            it["_toks"], it["_lead"], it["_nkey"], it["_dist"] = toks, lead, nkey, dist
            kept[kept.index(winner)] = it
        else:
            if it["source"] not in winner["also"] and it["source"] != winner["source"]:
                winner["also"].append(it["source"])
    for k in kept:
        for tmp in ("_toks", "_lead", "_nkey", "_dist"):
            k.pop(tmp, None)
    return kept


_UPGRADE_RE = re.compile(r"\bupgrad\w*|outlook (revised to )?(positive|stable)", re.IGNORECASE)
_DOWNGRADE_RE = re.compile(r"\bdowngrad\w*|defaults?\b|outlook (revised to )?negative|"
                           r"rating watch|delays? (in )?(payment|repayment)", re.IGNORECASE)


def _event_badge(it: dict) -> str:
    """Event tags were removed from the card at the reader's request. Kept as
    a function (unused in rendering) because _event_of still drives ordering."""
    key, label, _score, colour = _event_of(it)
    if not label:
        return ""
    # Direction matters for a rating action — up and down are not the same news.
    if key == "RATING":
        text = f'{it.get("title","")} {it.get("summary","")}'
        if _DOWNGRADE_RE.search(text):
            colour, label = "#b91c1c", "&#9660; RATING"
        elif _UPGRADE_RE.search(text):
            colour, label = "#15803d", "&#9650; RATING"
    return (f'<span style="color:{colour};font-size:9px;font-weight:800;'
            f'letter-spacing:1px;">{label}</span> ')


def _undated_note(it: dict) -> str:
    return ('<span style="color:#b0aa9c;font-size:9px;"> &middot; date unconfirmed</span>'
            if _is_undated(it) else "")


def _rating_badge(it: dict) -> str:
    """Small badge ahead of the headline for rating actions (credit desks
    care about these first)."""
    text = it["title"] + " " + it["summary"]
    if not _RATING_ACTION_RE.search(text):
        return ""
    if _DOWNGRADE_RE.search(text):
        return ('<span style="color:#cc0000;font-size:9px;font-weight:800;'
                'letter-spacing:1px;">&#9660; RATING ACTION</span> ')
    if _UPGRADE_RE.search(text):
        return ('<span style="color:#15803d;font-size:9px;font-weight:800;'
                'letter-spacing:1px;">&#9650; RATING ACTION</span> ')
    return ('<span style="color:#b45309;font-size:9px;font-weight:800;'
            'letter-spacing:1px;">&#9679; RATING ACTION</span> ')


def _rating_first(sec_items: list[dict]) -> list[dict]:
    """Most material first; an undated item never outranks a dated one of the
    same materiality, and never leads."""
    return sorted(sec_items, key=lambda it: (-_materiality(it), _is_undated(it)))


_STATS_PATH = os.path.join(_REPO_ROOT, "data", "team_stats.json")


def _append_stats(stats: dict) -> None:
    try:
        hist = []
        if os.path.exists(_STATS_PATH):
            with open(_STATS_PATH, encoding="utf-8") as f:
                hist = json.load(f)
        hist = (hist + [stats])[-30:]
        os.makedirs(os.path.dirname(_STATS_PATH), exist_ok=True)
        with open(_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=1)
        _git_push(_STATS_PATH)
    except Exception as exc:
        print(f"[stats] non-fatal: {exc}")


def _send_weekly_stats(now: "datetime.datetime") -> None:
    """Saturday: quality digest for the admin — per-source health, drop
    counts, delivery/failure counts for the last 7 runs."""
    try:
        with open(_STATS_PATH, encoding="utf-8") as f:
            hist = json.load(f)[-7:]
    except Exception:
        return
    rows = ""
    for s in hist:
        srcs = s.get("source_summary", {})
        dead = ", ".join(k for k, v in srcs.items() if v == 0) or "&mdash;"
        failed_html = ""
        if s.get("failed"):
            failed_html = (', <b style="color:#cc0000">'
                           f'{len(s["failed"])} failed</b>')
        rows += (f'<tr><td style="padding:6px;border-bottom:1px solid #eee;">{s.get("date")}</td>'
                 f'<td style="padding:6px;border-bottom:1px solid #eee;">{s.get("fetched", "?")}</td>'
                 f'<td style="padding:6px;border-bottom:1px solid #eee;">junk {s.get("junk", 0)} &middot; '
                 f'geo {s.get("geo", 0)} &middot; stale {s.get("stale", 0)} &middot; dup {s.get("dup", 0)}</td>'
                 f'<td style="padding:6px;border-bottom:1px solid #eee;">{s.get("mails", 0)} sent{failed_html}</td>'
                 f'<td style="padding:6px;border-bottom:1px solid #eee;color:#cc0000;font-size:11px;">'
                 f'{dead}</td></tr>')
    # (I) What the filters THREW AWAY — the only way to catch an over-tuned
    # gate, since a false negative never appears in the report itself.
    fn_rows = ""
    for entry in reversed(hist):
        ds = entry.get("dropped_samples") or {}
        for kind in ("relevance", "junk"):
            for t in (ds.get(kind) or [])[:8]:
                fn_rows += (f'<tr><td style="padding:4px 6px;border-bottom:1px solid #f0f0f0;'
                            f'font-size:11px;color:#888;white-space:nowrap;">{entry.get("date")}'
                            f' &middot; {kind}</td>'
                            f'<td style="padding:4px 6px;border-bottom:1px solid #f0f0f0;'
                            f'font-size:11px;color:#222;">{_esc(t)}</td></tr>')
        if len(fn_rows) > 12000:
            break
    fn_block = (
        f'<h3 style="font-family:Georgia,serif;margin-top:26px;">Dropped by the filters '
        f'&mdash; review for false negatives</h3>'
        f'<p style="font-size:11px;color:#777;margin:0 0 8px;">If anything here belongs in '
        f'the report, the relevance gate or junk filter is too tight. If anything here is '
        f'noise you keep seeing, add it to <code>suppress.json</code>.</p>'
        f'<table cellspacing="0" style="border-collapse:collapse;width:100%;">{fn_rows}</table>'
    ) if fn_rows else ""

    html = (f'<html><body style="font-family:Arial,sans-serif;font-size:13px;color:#222;">'
            f'<h2 style="font-family:Georgia,serif;">CareEdge Daily News &mdash; weekly quality report</h2>'
            f'<table cellspacing="0" style="border-collapse:collapse;width:100%;font-size:12px;">'
            f'<tr style="background:#1a1a1a;color:#fff;"><th style="padding:6px;text-align:left;">Date</th>'
            f'<th style="padding:6px;text-align:left;">Fetched</th><th style="padding:6px;text-align:left;">Dropped</th>'
            f'<th style="padding:6px;text-align:left;">Mails</th><th style="padding:6px;text-align:left;">Sources with 0 items</th></tr>'
            f'{rows}</table>'
            f'{fn_block}'
            f'<p style="color:#888;font-size:11px;">Auto-generated every Saturday. '
            f'<a href="{_MANAGE_URL}">Console</a> &middot; <a href="{_ARCHIVE_URL}">Archive</a></p></body></html>')
    admin = _admin_addr()
    if admin:
        try:
            _send(admin, f"CareEdge Daily News — weekly quality report ({now:%d %b %Y})", html)
        except Exception as exc:
            print(f"[stats] weekly mail failed: {exc}")


def _write_archive(archive_html: str, today: "datetime.date") -> None:
    """Publish today's master edition to docs/archive/ (GitHub Pages)."""
    try:
        adir = os.path.join(_REPO_ROOT, "docs", "archive")
        os.makedirs(adir, exist_ok=True)
        fname = f"{today.isoformat()}.html"
        with open(os.path.join(adir, fname), "w", encoding="utf-8") as f:
            f.write(archive_html)
        editions = sorted((n for n in os.listdir(adir) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", n)),
                          reverse=True)
        links = "".join(f'<li style="margin:4px 0;"><a href="{n}" style="color:#1e3a8a;">'
                        f'{n[:-5]}</a></li>' for n in editions[:90])
        index = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>CareEdge Daily News — Archive</title></head>'
                 f'<body style="font-family:Georgia,serif;max-width:640px;margin:40px auto;color:#222;">'
                 f'<h1 style="border-bottom:3px double #111;padding-bottom:8px;">CareEdge Daily News &mdash; Past Editions</h1>'
                 f'<ul style="list-style:none;padding:0;font-size:15px;">{links}</ul></body></html>')
        with open(os.path.join(adir, "index.html"), "w", encoding="utf-8") as f:
            f.write(index)
        _git_push(adir)
        print(f"[archive] published docs/archive/{fname}")
    except Exception as exc:
        print(f"[archive] non-fatal: {exc}")


def _story_score(it: dict) -> int:
    """Retained name; now delegates to the shared materiality score so the
    email's Top-5 and the newspaper's ordering can never disagree."""
    return _materiality(it)


def _legacy_story_score(it: dict) -> int:
    """Rank stories for the Top-5 table the way the AI ranks its takeaways:
    watchlist first, then penalties/rating actions, then regulatory."""
    text = it["title"] + " " + it["summary"]
    s = 0
    if it.get("companies"):
        s += 4
    if _PENALTY_RE.search(text):
        s += 3
    if _RATING_ACTION_RE.search(text):
        s += 3
    if it.get("section") == "S3":
        s += 2
    if it.get("section") in ("S4", "S5"):
        s += 1
    if "[T1]" in it.get("tags", ""):
        s += 1
    return s


def _esc(s: str) -> str:
    """Everything below is scraped text — Google News summaries in particular
    arrive as raw HTML fragments ('<a href="…'), which previously went into
    the card unescaped and shredded the markup (a truncated tag swallowed the
    real Read-more link). Escape every interpolated value."""
    return _html.escape(str(s or ""), quote=True)


_ALSO_REPORTED_CAP = 3


def _np_card(it: dict, hero: bool = False, company: str = "",
             takeaway: str = "") -> str:
    # Same materiality >= 8 threshold and red-flag treatment the S1 table
    # rows use, applied to S2/S3 cards -- a high-materiality regulatory
    # action or default signal shouldn't read as visually identical to a
    # routine sector story just because it isn't in S1.
    risky = _materiality(it) >= 8
    cls = "art hero" if hero else "art"
    if risky:
        cls += " risk"
    flag = '<span class="flag">&#9679; ACTION</span>' if risky else ""
    # Reference layout: "SOURCE | DATE" with a thin pipe and the DATE in
    # teal, rather than one flat grey run separated by bullets.
    lead = [_esc(b) for b in (company.upper() if company else "", it["source"]) if b]
    sep = '<span class="pipe">|</span>'
    meta = sep.join(lead)
    pub = _esc(it.get("pub", ""))
    if pub:
        meta = f'{meta}{sep}<span class="dt">{pub}</span>' if meta else f'<span class="dt">{pub}</span>'
    # Category label for S2/S3 only — a small tag, not a redesign, so a
    # reader scanning the section sees WHAT KIND of story this is without
    # opening it (spec: taxonomy per section, minimal visual change).
    cat = it.get("category")
    cat_tag = (f'<span class="cat" style="color:{_NP_TEAL_DK};font-weight:700;'
               f'font-size:8.5px;letter-spacing:0.6px;text-transform:uppercase;">'
               f' &middot; {_esc(cat)}</span>') if cat else ""
    bits = [meta] if meta else []
    link = (f'<a class="rm" href="{_esc(it["url"])}" target="_blank">Read more &#8594;</a>'
            if it["url"] else "")
    fb = _feedback_link(it)
    # Capped at 3: a duplicate story reported by seven or ten outlets is
    # still one card, not a wall of source names — the reader needs to know
    # it is corroborated, not the full syndication list.
    also_list = (it.get("also") or [])[:_ALSO_REPORTED_CAP]
    also = (f'<br><span class="also">Also reported by: '
            f'{_esc(", ".join(also_list))}</span>' if also_list else "")
    # No filler line when a feed gives no description — just omit it.
    summary = _esc(it["summary"])
    body = f'<p class="wh">{summary}</p>' if summary else ""
    # Credit lens: only for the top handful of stories per section (passed
    # in by the caller), only when the AI takeaway pass produced one. Never
    # a paraphrase of the headline — that constraint lives in the prompt.
    lens = (f'<p class="lens" style="color:{_NP_NAVY};font-size:10.5px;'
            f'font-weight:600;margin:3px 0 0;">Credit lens: {_esc(takeaway)}</p>'
            if takeaway else "")
    return (f'<div class="{cls}"><p class="src">{"".join(bits)}{cat_tag}{_undated_note(it)}{flag}</p>'
            f'<p class="hl">{_esc(it["title"])}</p>'
            f'{body}{lens}{link}{fb}{also}</div>')


_S1_RISK_TEMPLATES = {
    "DEFAULT": "Default/payment-stress signal — directly material to credit quality.",
    "REGULATORY": "Regulatory action — raises compliance and reputational risk; check the "
                  "penalty quantum and any operating restrictions attached.",
    "MANAGEMENT": "Leadership/governance change — a continuity risk to watch, not on its "
                  "own a credit event.",
    "FUNDING": "Fresh funding supports liquidity; check tenor and cost for any sign of "
               "wholesale-market stress rather than routine refinancing.",
    "M&A": "Ownership or structural change — the credit profile may shift with the new "
           "promoter/parent.",
    "RESULTS": "Quarterly numbers — check the asset-quality trend (GNPA/NNPA) and "
               "profitability for any deterioration behind the headline figure.",
}


# Mechanical mapping from the free regex event taxonomy (_event_of) to
# the same key_credit_variable_affected enum the AI path uses -- fallback
# only, used when neither a RATING direction nor a _VARIABLE_RULES
# keyword match applies. RATING/M&A map to "other": a rating action or
# ownership change is a meta-/structural event, not itself one of the
# underlying fundamentals in the list.
_EVENT_TO_VARIABLE = {
    "DEFAULT": "liquidity", "RATING": "other", "REGULATORY": "regulatory",
    "MANAGEMENT": "governance", "FUNDING": "funding", "M&A": "other",
    "RESULTS": "profitability",
}

# Direct keyword-to-variable rules, checked before the coarser
# _EVENT_TO_VARIABLE fallback -- lets a headline like "...rating
# downgraded... on asset quality stress" tag asset_quality, not the
# generic "other" a bare RATING event match alone would produce. Ordered:
# first match wins, most specific patterns first.
_VARIABLE_RULES = [
    ("asset_quality", re.compile(
        r"\b(npa|gnpa|nnpa|asset quality|stressed asset|slippage|bad loan|"
        r"write[- ]?off|provisioning|non[- ]?performing)\b", re.IGNORECASE),
     "Signals asset-quality deterioration — check the GNPA/NNPA trend and "
     "provisioning coverage."),
    ("liquidity", re.compile(
        r"\b(liquidity|cash flow|payment delay|missed payment|repayment|"
        r"asset[- ]liability mismatch|\balm\b|debt restructur|moratorium|"
        r"one[- ]?time settlement)\b", re.IGNORECASE),
     "Signals liquidity/repayment stress — a direct credit concern, not routine."),
    ("capital", re.compile(
        r"\b(capital adequacy|\bcrar\b|\bcar\b|capital infusion|capital base|"
        r"net ?worth|equity (raise|infusion)|tier[- ]?(i|ii|1|2) capital)\b",
        re.IGNORECASE),
     "Affects the capital cushion — check whether it strengthens or thins the buffer."),
    ("leverage", re.compile(
        r"\b(leverage|debt[- ]to[- ]equity|gearing ratio|debt[- ]equity ratio)\b",
        re.IGNORECASE),
     "Moves the leverage/gearing profile — check direction against the entity's "
     "typical range."),
    ("funding", re.compile(
        r"\b(commercial paper|\bncds?\b|debentures?|\bbonds?\b|fund[- ]?rais\w*|"
        r"borrowing|credit line|refinanc\w*|preferential allotment|rights issue|"
        r"\bqip\b|securitisation)\b", re.IGNORECASE),
     "Adds to the funding mix — check tenor and cost for any sign of "
     "wholesale-market stress."),
    ("profitability", re.compile(
        r"\b(net profit|\bpat\b|\bnii\b|net interest income|earnings|margin|"
        r"\broe\b|\broa\b|quarterly results?)\b", re.IGNORECASE),
     "A profitability data point — check the trend, not just the single "
     "quarter's number."),
    ("growth", re.compile(
        r"\b(loan growth|disbursement|\baum\b growth|expands?|new branches?|"
        r"market share|portfolio growth)\b", re.IGNORECASE),
     "A growth signal — check whether it comes with any asset-quality trade-off."),
    ("governance", re.compile(
        r"\b(resign|steps? down|appoint\w*|board approv|auditor|whistleblow|"
        r"fraud|related[- ]party|governance)\b", re.IGNORECASE),
     "A governance/continuity signal — watch for follow-on rating-agency commentary."),
    ("regulatory", re.compile(
        r"\b(penalty|penalis|\bsebi\b|\brbi\b order|show cause|debarr|"
        r"licence (cancel|revok)|compliance|enforcement action|adjudication)\b",
        re.IGNORECASE),
     "Raises compliance/reputational risk — check the penalty quantum and any "
     "operating restrictions."),
    ("macro", re.compile(
        r"\b(\bgdp\b|inflation|repo rate|monetary policy|rbi policy|economic growth)\b",
        re.IGNORECASE),
     "A macro/systemic signal rather than entity-specific — read alongside "
     "sector-wide trends."),
]


def _mech_s1_view(it: dict) -> dict:
    """Rule-based credit read for the S1 Summary column, no API call
    involved -- same {variable, implication, why, commentary} shape
    _ai_s1_view_batch returns. This is the PRIMARY path when Anthropic
    credits are unavailable, not a degraded placeholder: _VARIABLE_RULES
    scans the actual text for the specific fundamental affected
    (asset quality, liquidity, capital, funding, etc), same taxonomy the
    AI path tags, before ever falling back to the coarser event-category
    mapping."""
    text = f'{it.get("title", "")} {it.get("summary", "")}'
    key, _label, score, _colour = _event_of(it)
    band = "High" if score >= 8 else "Moderate" if score >= 6 else "Low"

    variable, note = "other", ""
    for var, rx, implication in _VARIABLE_RULES:
        if rx.search(text):
            variable, note = var, implication
            break

    if key == "RATING":
        if _DOWNGRADE_RE.search(text):
            headline_read = ("Rating downgrade/negative outlook — signals credit "
                              "deterioration; check the driver and any covenant or "
                              "funding follow-through.")
        elif _UPGRADE_RE.search(text):
            headline_read = ("Rating upgrade/positive outlook — credit-positive; "
                              "confirm it reflects a structural improvement rather "
                              "than a one-off.")
        else:
            headline_read = ("Rating action (reaffirmation or watch) with no stated "
                              "change in credit view; watch for the next review outcome.")
        # The rating direction is always the headline read; a keyword match
        # (e.g. "asset quality stress" in the same sentence) still refines
        # WHICH variable moved, since that's the more useful tag here.
        implication = headline_read
    elif note:
        variable, implication = variable, note
    else:
        implication = _S1_RISK_TEMPLATES.get(
            key, "General development — no rating, funding, regulatory or governance "
                 "signal detected from the available text.")
        variable = _EVENT_TO_VARIABLE.get(key, "other")

    why = f"Risk read: {band}."
    return {
        "variable": variable,
        "implication": implication,
        "why": why,
        "commentary": f"{implication} {why}",
    }


def _np_s1_row(it: dict, company: str, view: dict | None = None) -> str:
    """One S1 watchlist row: Company | Source Link | Summary. Replaces the
    per-entity header + stacked cards for S1 specifically (team's requested
    table layout) — S2/S3 keep the 3-column card layout in _np_card, since
    those items don't belong to one company and a table doesn't fit them.

    view: {variable, implication, why, commentary} -- from _ai_s1_view_batch
    when AI is available, else _mech_s1_view. Same shape either way, so
    the row always shows a key_credit_variable_affected tag plus a real
    analytical commentary, never a copy of the headline.
    """
    # Materiality >= 8 is the same "needs action" threshold the old
    # per-entity header used -- reader feedback asked for this to read as a
    # clear risk flag, so the whole row is marked (red left rule + red
    # company name), not just a small badge under the name.
    risky = _materiality(it) >= 8
    row_cls = ' class="risk"' if risky else ""
    flag = '<span class="flag">&#9679; ACTION</span>' if risky else ""
    meta = " &middot; ".join(_esc(x) for x in (it["source"], it.get("pub", "")) if x)
    headline = (f'<a href="{_esc(it["url"])}" target="_blank">{_esc(it["title"])}</a>'
                if it["url"] else f'<span>{_esc(it["title"])}</span>')
    view = view or _mech_s1_view(it)
    # Defensive: callers pass the {variable, implication, why, commentary}
    # dict, but the email-body path carries the same keys flattened to a
    # plain commentary string. A str reaching here used to crash the whole
    # run on view.get(); accept both shapes instead so a caller mix-up
    # degrades to "renders the text" rather than "no newsletter today".
    if isinstance(view, str):
        view = {"commentary": view}
    # Reader feedback: no colour-tag chip -- the analysis prose itself is
    # the point, not a labelled badge ahead of it. key_credit_variable_
    # affected is still computed and available on `view` for any future
    # use (sorting, filtering), just not rendered as a visible tag here.
    summary = _esc((view.get("commentary") or "").strip()) or "&mdash;"
    also_list = (it.get("also") or [])[:_ALSO_REPORTED_CAP]
    also = (f'<span class="also">Also reported by: {_esc(", ".join(also_list))}</span>'
            if also_list else "")
    return (f'<tr{row_cls}><td class="company">{_esc(company)}{flag}</td>'
            f'<td class="link">{headline}'
            f'<span class="srcmeta">{meta}{_undated_note(it)}</span></td>'
            f'<td class="summary">{summary}{also}{_feedback_link(it)}</td></tr>')


def _feedback_link(it: dict) -> str:
    """(J) One click to flag an item as irrelevant. A mailto keeps this
    working with no server, no endpoint and no auth — the reply lands in the
    admin mailbox with the exact title, which goes straight into
    suppress.json."""
    import urllib.parse
    admin = _admin_addr()
    if not admin:
        return ""
    subj = urllib.parse.quote(f"[not relevant] {it.get('title','')[:120]}")
    return (f'<a href="mailto:{admin}?subject={subj}" '
            f'style="font-size:8px;color:#c9c4b8;text-decoration:none;'
            f'margin-left:8px;">not relevant?</a>')


def _request_entity_link(for_name: str = "", n_entities: int = 0) -> str:
    """Self-service route for readers who have no GitHub account.

    The console (docs/team.html) can already add entities, but saving needs
    a GitHub Personal Access Token — which means a GitHub account with write
    access to the repo. The desk's analysts have neither, so in practice
    only the admin could ever add an entity. This is the same mailto trick
    the 'not relevant?' link uses: no server, no endpoint, no auth, and the
    request lands in the admin mailbox pre-filled and ready to action in
    the console.

    Deliberately a REQUEST rather than a direct write: every entity costs a
    Google News query on every run, so the entity list is worth keeping
    under one pair of eyes.
    """
    import urllib.parse
    admin = _admin_addr()
    if not admin:
        return ""
    who = for_name or "(your name)"
    subj = urllib.parse.quote(f"[add entity] request from {who}")
    body = urllib.parse.quote(
        "Please add the following to my watchlist:\n\n"
        "Entity name (as registered, e.g. 'Shriram Finance Limited'):\n"
        "  1. \n"
        "  2. \n\n"
        "Remove from my watchlist (optional):\n"
        "  1. \n\n"
        f"Requested by: {who}\n")
    return (f'<p style="margin:16px 0 0;padding-top:8px;'
            f'border-top:1px solid {_NP_RULE};font-size:9px;'
            f'color:{_NP_MUTED};line-height:1.6;">'
            f'Tracking {n_entities} entit{"ies" if n_entities != 1 else "y"}. '
            f'<a href="mailto:{admin}?subject={subj}&amp;body={body}" '
            f'style="color:{_NP_TEAL_DK};font-weight:700;'
            f'text-decoration:none;">Request an entity &#8594;</a>'
            f'</p>')


_CATEGORY_ORDER = {
    "S2": [lbl for _c, lbl, _rx in _S2_TAXONOMY] + ["General"],
    "S3": [lbl for _c, lbl, _rx in _S3_TAXONOMY] + ["General"],
}
# Reader feedback: these S2 subheadings took up space without adding
# navigational value (the desk already scans S2 as one list). Items in
# these categories still render — categorised, ordered, everything else
# unchanged — just without a printed subsection label above them.
_NO_HEADING_CATEGORIES = {"Regulatory & Policy", "Microfinance & Retail Credit",
                          "Banks & NBFCs"}


def _category_header(label: str) -> str:
    """Lighter than _company_header — a subsection label within S2/S3, not
    an entity heading. Only rendered when at least one qualifying story
    exists in that category (the caller never calls this for an empty
    group)."""
    return (f'<p style="margin:13px 0 4px;font-size:8.5px;font-weight:700;'
            f'letter-spacing:1px;text-transform:uppercase;color:{_NP_TEAL_DK};'
            f'break-after:avoid;-webkit-column-break-after:avoid;'
            f'page-break-after:avoid;">{_esc(label)}</p>')


def _np_partb(p: dict, items: list[dict], by_section: dict,
              takeaways: dict | None = None, gpt_excluded: set | None = None
              ) -> tuple[str, int, list[dict]]:
    """Per-person Part B in the 7:30 class markup. Returns (html, story_count,
    the stories shown — used to pick the Top 5).

    gpt_excluded: item keys GPT was actually shown and judged not material
    enough to include in s2_summary/s3_summary -- these rows are dropped
    from the S2/S3 table entirely, not just left without an analysis line.
    Only items GPT actually evaluated are ever in this set: an item beyond
    the per-run cap, or any item at all when GPT is off/failed, was never
    judged and always stays in the table with the mechanical fallback --
    "GPT didn't look at it" must never be treated the same as "GPT looked
    and said skip it".
    """
    gpt_excluded = gpt_excluded or set()
    parts: list[str] = []
    chosen: list[dict] = []
    total = 0
    for sid, sbcls, skey, title in _NP_SECTIONS:
        # A section the reader has not subscribed to is omitted ENTIRELY —
        # no banner, no placeholder, and (via the empty bucket this leaves)
        # no page, no nav tab and no page number in the attachment. It used
        # to print "Not subscribed — enable this section in the console",
        # which cost a whole page of an S1-only reader's newsletter to say
        # nothing. A subscribed section with no news still renders its
        # banner plus "No news in this category today", so the two cases
        # stay distinguishable downstream.
        if skey not in p["sections"]:
            continue
        parts.append(f'<div id="{sid}" data-section="banner" class="sb {sbcls}">{title}</div>')
        if skey == "S1":
            # (F) Group by entity. A GH scanning 39 items wants "Shriram
            # Finance: 5 items" together, not five cards interleaved with
            # other names. A story matching two of their companies is still
            # shown once, under the first — hence the `shown` guard.
            by_company: dict[str, list[dict]] = {}
            shown: set[str] = set()
            for comp in sorted(p["companies"]):
                for it in items:
                    if comp in it["companies"] and _key(it) not in shown:
                        shown.add(_key(it))
                        by_company.setdefault(comp, []).append(it)
            if not by_company:
                # (C) "Nothing happened" is a real, useful answer — say it
                # plainly rather than leaving an empty-looking section.
                parts.append(
                    f'<p class="empty">No material developments across your '
                    f'{len(p["companies"])} entities today.</p>')
                parts.append(_request_entity_link(p.get("name", ""),
                                                  len(p["companies"])))
                continue
            n_items = sum(len(v) for v in by_company.values())
            total += n_items
            for v in by_company.values():
                chosen.extend(v)
            # Entities with the most material news first; within an entity,
            # most material first, and an undated item never leads.
            for v in by_company.values():
                v.sort(key=lambda it: (-_materiality(it), _is_undated(it)))
            order = sorted(by_company.items(),
                           key=lambda kv: -max(_materiality(i) for i in kv[1]))
            # Team-requested layout: Company / Source Link / Summary as a
            # table, one row per story, instead of per-entity header +
            # stacked cards. The table wrapper carries column-span:all so
            # it escapes the page's 3-column card layout entirely — a
            # table row can't sensibly split across columns the way a
            # card can. S2/S3 are unaffected; that layout doesn't fit
            # them (their items don't belong to one company), see the
            # layout-scope decision this replaced.
            rows = "".join(_np_s1_row(it, comp, (takeaways or {}).get(_key(it)))
                           for comp, its in order for it in its)
            parts.append(
                '<div class="s1wrap"><table class="s1tbl">'
                '<thead><tr><th>Company</th><th>Source Link</th><th>View/Implications</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>')
            # Closes the section the reader is most likely to notice a gap
            # in — "my entity isn't here" is exactly the moment to offer
            # the request link.
            parts.append(_request_entity_link(p.get("name", ""),
                                              len(p["companies"])))
        else:
            sec_items = by_section[skey]
            if skey == "S2" and p.get("sectors"):
                # A GH sees the sector(s) their own entities sit in.
                sec_items = [it for it in sec_items
                             if (it.get("sectors") or {_DEFAULT_SECTOR}) & p["sectors"]]
            if not sec_items:
                parts.append('<p class="empty">No news in this category today.</p>')
                continue
            # Team-requested layout (tried as a demo, now built for real):
            # S2/S3 as a Category / Source Link / Summary table, same
            # structure as the S1 watchlist table -- Category stands in
            # for Company, since these items don't belong to one entity.
            # Replaces the old category-subheader + 3-column card layout
            # entirely (_np_card/_category_header/_NO_HEADING_CATEGORIES
            # are left in the file, unused, as the known-working fallback
            # if this needs reverting).
            #
            # gpt_excluded is applied HERE, before total/chosen are
            # updated, so a GPT-judged-not-material item is dropped from
            # the story count and the Top-10 email-body candidate pool
            # too -- not just missing its analysis line while still
            # counting as "news" everywhere else.
            sec_items = [it for it in sec_items if _key(it) not in gpt_excluded]
            total += len(sec_items)
            chosen.extend(sec_items)
            sec_items = _rating_first(sec_items)
            rows = []
            for it in sec_items:
                cat = it.get("category") or "General"
                raw_view = (takeaways or {}).get(_key(it))
                view = {"commentary": raw_view} if raw_view else None
                rows.append(_np_s1_row(it, cat, view))
            parts.append(
                '<div class="s1wrap"><table class="s1tbl">'
                '<thead><tr><th>Category</th><th>Source Link</th><th>View/Implications</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')
    return "\n".join(parts), total, chosen


def _mech_digest(person_items: list[dict], n_entities: int) -> str:
    """Factual one-line digest — counts, not prose. With AI off there is no
    executive summary, and a bare Top-5 gives the reader no sense of scale
    or shape. This says how much arrived and what KIND, derived entirely
    from the event taxonomy: no API, nothing that can be hallucinated."""
    # S1 only. The digest sits under "TODAY AT A GLANCE" and is read as a
    # statement about the reader's OWN entities; counting S2/S3 in it made
    # the number meaningless ("108 items across your 47 entities" when most
    # of those were shared sector and macro stories).
    person_items = [it for it in person_items if it.get("section") == "S1"]
    if not person_items:
        return ""
    counts: dict = {}
    for it in person_items:
        key, _label, _s, _c = _event_of(it)
        if key != "OTHER":
            counts[key] = counts.get(key, 0) + 1
    # Bare lowercased labels read wrong at both counts: RESULTS is already
    # plural ("1 results"), the rest are bare adjectives/singular nouns
    # with no plural form ("3 rating", "2 funding") -- confirmed directly
    # from a delivered digest line. Explicit singular/plural noun phrases
    # per event, matched by count.
    _NOUNS = {
        "DEFAULT": ("default", "defaults"),
        "RATING": ("rating action", "rating actions"),
        "REGULATORY": ("regulatory action", "regulatory actions"),
        "MANAGEMENT": ("management change", "management changes"),
        "FUNDING": ("funding update", "funding updates"),
        "M&A": ("M&A update", "M&A updates"),
        "RESULTS": ("result", "results"),
    }
    order = [key for key, _lbl, _s, _c, _rx in _EVENTS]
    parts = []
    for key in order:
        n_key = counts.get(key)
        if not n_key:
            continue
        sing, plur = _NOUNS[key]
        parts.append(f"{n_key} {sing if n_key == 1 else plur}")
    n = len(person_items)
    head = f"{n} item{'s' if n != 1 else ''} across your {n_entities} entit{'ies' if n_entities != 1 else 'y'}"
    return f"{head} — {', '.join(parts)}." if parts else f"{head}."


def _np_partc(top5: list[dict], date_str: str, takeaways: dict | None = None,
             exec_summary: str = "", watchlist_html: str = "") -> str:
    """Top-5 table in the exact Part C markup the 7:30 email body uses, plus
    an AI executive summary paragraph above it and a one-line "why this
    matters" under each headline.

    (The three-band Action/Watch/Context layout was tried and removed at the
    reader's request — this is the original single ranked list. Ordering
    still comes from the shared materiality score, so the most material item
    is number 01.) takeaways/exec_summary are both optional and empty by
    default, so a run with no API access renders exactly as before.

    watchlist_html: optional short "needs analyst attention" note (from
    GPT's email_body.watchlist_attention), rendered as its own small block
    under the exec summary. Empty by default -- omitted entirely when there
    is nothing that genuinely merits it, same principle as exec_summary.
    """
    takeaways = takeaways or {}
    rows = ""
    for i, it in enumerate(top5):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(top5) - 1 else ""
        label = SECTION_TITLES.get(it.get("section", "S2"), "News").upper()
        # Event type is derived mechanically from the existing taxonomy and
        # IS the credit angle: a reader scanning five lines wants RATING /
        # DEFAULT / REGULATORY visible at a glance. Free, no API call, and
        # nothing here can be hallucinated — the honest stand-in for the AI
        # line whenever AI is off.
        ev_key, ev_label, _ev_score, ev_colour = _event_of(it)
        ev_html = (f'<span style="display:inline-block;padding:1px 5px;margin-left:6px;'
                   f'border:1px solid {ev_colour};color:{ev_colour};border-radius:2px;'
                   f'font-size:8px;font-weight:800;letter-spacing:0.5px;">{ev_label}</span>'
                   if ev_key != "OTHER" else "")
        why = takeaways.get(_key(it), "")
        why_html = (f'<p style="margin:4px 0 0;font-size:11.5px;color:#444;'
                   f'line-height:1.55;font-style:italic;">{_esc(why)}</p>' if why else "")
        rows += (
            f'<tr valign="top">'
            f'<td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;'
            f'color:#cc0000;line-height:1;font-family:Georgia,serif;width:44px;">{i + 1:02d}</td>'
            f'<td style="padding:10px 16px 10px 4px;{border}">'
            f'<p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;'
            f'text-transform:uppercase;color:#888;">{label} &bull; {_esc(it["source"])}{ev_html}</p>'
            f'<p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">{_esc(it["title"])}</p>'
            f'{why_html}'
            f'</td></tr>'
        )
    if not rows:
        rows = ('<tr><td style="padding:10px 16px;color:#1a1a1a;font-size:12px;">'
                'No fresh items in your sections today.</td></tr>')
    watchlist_block = (
        f'<p style="margin:10px 0 0;font-size:9px;font-weight:800;letter-spacing:2px;'
        f'text-transform:uppercase;color:#b45309;">&#9679; Watchlist Attention</p>'
        f'<p style="margin:0;font-size:12.5px;color:#333;line-height:1.65;'
        f'font-family:Georgia,serif;">{_esc(watchlist_html)}</p>'
        if watchlist_html else ""
    )
    summary_block = (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #e5e5e5;border-left:3px solid #b45309;'
        f'border-bottom:none;background:#fbf7ef;">'
        f'<tr><td style="padding:14px 16px 12px;">'
        f'<p style="margin:0 0 5px;font-size:9.5px;font-weight:800;letter-spacing:2px;'
        f'text-transform:uppercase;color:#b45309;">&#9679; TODAY AT A GLANCE</p>'
        f'<p style="margin:0;font-size:12.5px;color:#333;line-height:1.65;'
        f'font-family:Georgia,serif;">{_esc(exec_summary)}</p>'
        f'{watchlist_block}'
        f'</td></tr></table>' if exec_summary else ""
    )
    heading = f"TOP {len(top5)} HEADLINES" if top5 else "HEADLINES"
    return (
        f'{summary_block}'
        f'<table id="takeaways" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">'
        f'<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;'
        f'text-transform:uppercase;color:#fff;">&#9679; {heading} &mdash; {date_str}</td></tr>'
        f'</table>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #e5e5e5;border-top:none;">{rows}</table>'
    )


def _np_build_attachment(part_b_html: str, today, for_name: str = "",
                         masthead: str = "CareEdge Daily News",
                         coverage_note: str = "", sections=None) -> str:
    """Newspaper covering the sections the reader is subscribed to.

    send_credit_report.build_attachment() is hardcoded to five pages with an
    S4/S5 nav, and that file is not to be modified — so the team mail builds
    its own. Same visual language.

    sections: which of S1/S2/S3 this reader gets. Unsubscribed sections are
    dropped completely — no page, no nav tab, no page number — so an
    S1-only reader receives a genuine one-page newspaper rather than a
    three-page one whose last two pages say "not subscribed". Page numbers
    and the "Page X of N" footer are computed from the surviving sections,
    so they always read 1..N with no gaps. Defaults to all three (the
    master/archive edition).

    for_name puts the recipient on the masthead — every edition is
    personalised to that reader's entities, so it should say whose it is.
    masthead/coverage_note let the Monday run rebrand itself as the Weekend
    Edition and say what span of days it covers, since it is not a normal
    single day's news.
    """
    sections = set(sections) if sections else {"S1", "S2", "S3"}
    date_str = today.strftime("%d %B %Y")
    dow_full = today.strftime("%A, %d %B %Y").upper()
    edition = f"Vol. {today.year} &middot; Internal Use Only"

    # Split the rendered part B on the section-banner ids.
    buckets = {sid: "" for sid, _, _ in _NP_PAGES}
    positions = {}
    for sid, _, _ in _NP_PAGES:
        m = re.search(rf'<[^>]+\bid=["\']({sid})["\'][^>]*>', part_b_html)
        if m:
            positions[sid] = m.start()
    ordered = sorted(positions.items(), key=lambda x: x[1])
    for i, (sid, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(part_b_html)
        buckets[sid] = part_b_html[start:end].strip()
    empty = ('<p style="padding:20px 0;font-size:11px;color:#aaa;'
             'font-style:italic;">No news in this category today.</p>')

    # Only the subscribed sections become pages, renumbered 1..N so an
    # S1+S3 reader gets pages 1 and 2 (not 1 and 3), and the footer says
    # "Page 1 of 2". The first surviving section always gets the front-page
    # masthead treatment, whichever section it happens to be.
    active = [(sid, title) for sid, title, _pnum in _NP_PAGES
              if sid.upper() in sections]
    if not active:                      # nobody subscribed to anything
        active = [(_NP_PAGES[0][0], _NP_PAGES[0][1])]
    n_pages = len(active)

    nav = "".join(
        f'<a href="#pg{i}">{t}</a>' for i, (_sid, t) in enumerate(active, 1))
    # Masthead strapline lists only the sections actually in this edition.
    strap_names = {"s1": "S1 Watchlist", "s2": "S2 Sector", "s3": "S3 Macro"}
    strap = " &middot; ".join(strap_names[sid] for sid, _t in active)

    pages = ""
    for idx, (sid, title) in enumerate(active, 1):
        pnum = str(idx)
        content = buckets.get(sid) or empty
        if idx == 1:
            pages += f"""
<div class="news-page front-page" id="pg1">
  <div class="mast-top">
    <div class="mast-left"><span class="mast-eyebrow-ic">&#9679;</span>{dow_full}<br>{edition}</div>
    <div class="mast-right">Credit &amp; Markets Intelligence</div>
  </div>
  <div class="mast-center">
    <div class="mast-name">{_esc(masthead)}</div>
    <hr class="mast-rule">
  </div>
  <div class="mast-sub">
    <span>{strap}{f' &middot; {_esc(coverage_note)}' if coverage_note else ''}</span>
    <span class="red">CONFIDENTIAL</span>
  </div>
  <nav class="navbar">{nav}</nav>
  <!-- Repeats at the top of every subsequent physical page via CSS
       running elements (position:running/element()) -- takes no space
       here itself. A reader who lands on page 6 of an S1 section that
       overflowed far past page 1 would otherwise see a bare table with
       no title, date or section context at all. -->
  <div class="runhead">{_esc(masthead)} &middot; {title} &middot; {date_str}</div>
  <div class="columns">{content}</div>
  <div class="page-foot">
    <span>CareEdge Daily News &mdash; {date_str}</span>
    <span>Page 1 of {n_pages}</span><span>Confidential</span>
  </div>
</div>"""
        else:
            pages += f"""
<div class="news-page" id="pg{pnum}">
  <div class="page-header">
    <div class="ph-meta">{date_str} &bull; Internal Use Only</div>
    <div class="ph-title">{title}</div>
    <div class="ph-num">{pnum}</div>
  </div>
  <div class="runhead">{_esc(masthead)} &middot; {title} &middot; {date_str}</div>
  <div class="columns">{content}</div>
  <div class="page-foot">
    <span>{_esc(masthead)} &mdash; {date_str}</span>
    <span>Page {pnum} of {n_pages}</span><span>Confidential</span>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{_esc(masthead)} — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=PT+Serif:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  /* Continuation pages (a section overflowing past one physical page)
     reserve top space for the slim running header and repeat it there.
     WeasyPrint does not support "@page :not(:first)" as a selector (it
     silently drops the whole rule, confirmed directly against a minimal
     isolated test) -- so the reservation applies to every page here, and
     is explicitly cleared back on :first below, which is the pattern
     WeasyPrint does support. Page 1 does not need it: it already carries
     the full masthead inline. */
  @page {{ size: A4; margin: 1.2cm 1.4cm; margin-top: 1.9cm; }}
  @page {{ @top-center {{ content: element(runhead); width: 100%; }} }}
  @page :first {{ margin-top: 0.5cm; }}
  @page :first {{ @top-center {{ content: none; }} }}
  .runhead {{ position: running(runhead); font-size:8.5px; font-weight:700;
    letter-spacing:1px; text-transform:uppercase; color:{_NP_MUTED};
    padding:8px 28px; border-bottom:1px solid {_NP_RULE}; background:#fff; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#eef1f4;font-family:'PT Serif',Georgia,'Noto Serif',serif;color:{_NP_INK};font-size:11px}}
  .newspaper{{max-width:960px;margin:20px auto}}
  .news-page{{background:#ffffff;box-shadow:0 2px 24px rgba(0,0,0,.18);margin-bottom:28px;padding-bottom:20px;break-before:page;page-break-before:always}}
  .front-page{{break-before:auto;page-break-before:auto}}
  .mast-top{{display:flex;justify-content:space-between;align-items:flex-end;padding:14px 28px 6px;border-bottom:1px solid #aaa}}
  .mast-left{{font-size:8.5px;letter-spacing:1.5px;text-transform:uppercase;color:#555;line-height:1.8}}
  .mast-eyebrow-ic{{color:{_NP_TEAL_DK};margin-right:6px;font-size:8px}}
  .mast-right{{font-size:8.5px;text-align:right;color:#555;line-height:1.8}}
  .mast-center{{text-align:center;padding:4px 28px 0}}
  .mast-name{{font-family:'Playfair Display',Georgia,serif;font-size:52px;font-weight:900;line-height:1;letter-spacing:-2px;color:{_NP_NAVY}}}
  .mast-rule{{border:none;border-top:2px solid {_NP_TEAL};margin:6px 0 0}}
  .mast-sub{{display:flex;justify-content:space-between;align-items:center;padding:5px 28px;border-bottom:1px solid {_NP_RULE};font-size:8.5px;letter-spacing:1px;text-transform:uppercase;color:#555}}
  .mast-sub .red{{color:#D0021B;font-weight:700;letter-spacing:1.5px}}
  .navbar{{display:flex;background:{_NP_NAVY_DEEP}}}
  .navbar a{{flex:1;text-align:center;padding:10px 6px;font-size:8.5px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#C6D3DE;text-decoration:none;border-right:1px solid rgba(255,255,255,.10);white-space:nowrap}}
  .navbar a:first-child{{background:{_NP_TEAL};color:{_NP_NAVY_DEEP}}}
  .art .src .pipe{{color:{_NP_RULE};margin:0 7px;font-weight:400}}
  .art .src .dt{{color:{_NP_TEAL_DK};font-weight:700}}
  .navbar a:last-child{{border-right:none}}
  .page-header{{display:flex;justify-content:space-between;align-items:center;padding:8px 28px;border-bottom:1px solid {_NP_RULE};border-top:3px solid {_NP_NAVY}}}
  .page-header .ph-meta{{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:#777}}
  .page-header .ph-title{{font-family:'Playfair Display',Georgia,serif;font-size:14px;font-weight:700;color:#111}}
  .page-header .ph-num{{font-size:26px;font-weight:900;font-family:'Playfair Display',Georgia,serif;color:{_NP_TEAL};line-height:1}}
  .columns{{padding:0 28px 8px;column-count:3;column-gap:22px;column-rule:1px solid {_NP_RULE};min-height:80px}}
  [data-section="banner"]{{column-span:all;margin:20px -28px 0;padding:5px 28px;border-top:3px solid;border-bottom:1px solid}}
  /* S1 watchlist table -- Company / Source Link / Summary, one row per
     story. column-span:all pulls it out of the 3-column card layout used
     by S2/S3, which a table row can't split across the way a card can. */
  .s1wrap{{column-span:all;overflow-x:auto;margin-top:6px}}
  table.s1tbl{{width:100%;border-collapse:collapse;font-size:11px}}
  table.s1tbl th{{background:{_NP_TEAL_DK};color:#fff;font-family:Arial,Helvetica,sans-serif;
    font-weight:700;font-size:9px;letter-spacing:.7px;text-transform:uppercase;
    text-align:left;padding:8px 12px}}
  table.s1tbl td{{padding:9px 12px;border-bottom:1px solid {_NP_RULE};vertical-align:top;
    color:{_NP_BODY};line-height:1.5}}
  table.s1tbl tr:nth-child(even) td{{background:#FAFBFC}}
  table.s1tbl td.company{{font-family:Georgia,serif;font-weight:700;color:{_NP_INK};
    font-size:11px;width:16%}}
  table.s1tbl td.company .flag{{color:#D0021B;font-weight:800;font-size:7.5px;
    display:block;margin-top:2px;letter-spacing:.5px}}
  /* Risk flag: materiality >= 8 -- the whole row reads red, not just a
     small badge, so a reader scanning the Company column can't miss it. */
  table.s1tbl tr.risk td{{border-left:3px solid #D0021B}}
  table.s1tbl tr.risk td.company{{color:#D0021B}}
  table.s1tbl td.link{{width:30%}}
  table.s1tbl td.link a{{color:{_NP_TEAL_DK};font-weight:700;text-decoration:none;font-size:10.5px}}
  table.s1tbl td.link .srcmeta{{display:block;margin-top:3px;font-size:8.5px;color:{_NP_MUTED}}}
  table.s1tbl td.summary{{width:54%;font-size:10.3px}}
  table.s1tbl td.summary .also{{display:block;margin-top:3px;color:{_NP_MUTED};font-size:9px}}
  .sb{{font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;padding-top:6px;padding-bottom:6px}}
  .sb1{{color:{_NP_NAVY};border-color:{_NP_TEAL}}}
  .sb2{{color:{_NP_NAVY};border-color:{_NP_TEAL}}}
  .sb3{{color:{_NP_NAVY};border-color:{_NP_TEAL}}}
  .art{{break-inside:avoid;padding:12px 0;border-bottom:1px solid {_NP_RULE}}}
  .art .src{{margin:0 0 3px;font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;color:{_NP_MUTED}}}
  .art .hl{{margin:0 0 6px;font-size:12.8px;font-weight:650;font-family:Georgia,serif;line-height:1.28;color:{_NP_INK}}}
  .art .wh{{margin:0 0 5px;font-size:10.5px;color:{_NP_BODY};line-height:1.55}}
  .art .rm{{font-size:9px;color:{_NP_TEAL_DK};text-decoration:none;font-weight:700}}
  .art .also{{font-size:10px;color:{_NP_MUTED}}}
  .art.hero{{padding:12px 0 14px;border-bottom:1px solid {_NP_TEAL};margin-bottom:4px}}
  .art.hero .src{{color:{_NP_MUTED}}}
  .art.hero .hl{{font-size:16.4px;font-weight:800;line-height:1.24}}
  .art.hero .wh{{font-size:11px;color:{_NP_BODY};line-height:1.7}}
  .art.hero .rm{{color:{_NP_TEAL_DK};font-weight:700}}
  /* Risk flag: materiality >= 8, same threshold and red treatment the S1
     table rows use -- a left rule plus a red headline, not just a small
     badge, so a reader scanning the column can't miss it. */
  .art.risk{{border-left:3px solid #D0021B;padding-left:10px}}
  .art.risk .hl{{color:#D0021B}}
  .art .flag{{color:#D0021B;font-weight:800;font-size:7.5px;letter-spacing:.5px}}
  .ibh{{margin:14px 0 4px;font-size:8px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#999}}
  .ib{{margin:0 0 4px;font-size:9.5px;color:#555;line-height:1.5}}
  .ib a{{color:#999;font-size:8.5px;text-decoration:none}}
  .empty{{padding:10px 0;font-size:10px;color:#aaa;font-style:italic}}
  .page-foot{{display:flex;justify-content:space-between;border-top:2px solid {_NP_TEAL};margin:8px 28px 0;padding-top:6px;font-size:8px;color:#888;letter-spacing:1px;text-transform:uppercase}}
  @media print {{ body{{background:#fff}} .news-page{{box-shadow:none;margin-bottom:0}} }}
</style></head>
<body><div class="newspaper">{pages}</div></body></html>"""


def _np_rebrand(html: str) -> str:
    """The 7:30 templates carry the 'Credit Intelligence News' masthead and
    repo-edit links; this mail is branded CareEdge Daily News and managed
    from the team console."""
    html = html.replace("Credit Intelligence News", "CareEdge Daily News")
    # Masthead redesign: send_credit_report.py's build_email() renders a
    # plain white nameplate (near-black text, #999 grey eyebrow) which
    # reads flat next to the red top bar -- per reader feedback. Styled
    # via post-processing string replacement rather than editing
    # build_email() itself, since that file is shared with the 7:30
    # report and must not change. Both replaced strings are unique to
    # the masthead block within build_email()'s output.
    html = html.replace(
        '<td style="padding:12px 20px 10px;">\n  <p style="margin:0 0 3px;'
        'font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;">',
        '<td style="padding:18px 20px 16px;background:#1a1a1a;">\n  '
        '<p style="margin:0 0 4px;font-size:9px;letter-spacing:2px;'
        'text-transform:uppercase;color:#e8a33d;">',
    )
    html = html.replace(
        'font-size:28px;font-weight:900;color:#1a1a1a;letter-spacing:-1px;'
        'line-height:1;font-family:Georgia,serif;">CareEdge Daily News</p>',
        'font-size:30px;font-weight:900;color:#fff;letter-spacing:-0.5px;'
        'line-height:1;font-family:Georgia,serif;">CareEdge Daily News</p>',
    )
    for stale in (
        "https://github.com/mjitendrafeb-cmd/jeetz/edit/main/config.json",
        "https://github.com/mjitendrafeb-cmd/jeetz/edit/main/watchlist.txt",
    ):
        html = html.replace(stale, _MANAGE_URL)
    html = html.replace(
        "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/daily_credit_report.yml",
        "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/team_news.yml",
    )
    html = html.replace(
        "S1 Watchlist \u00b7 S2 NBFC/FI \u00b7 S3 Regulations \u00b7 S4 Markets \u00b7 S5 Macro",
        "S1 Watchlist \u00b7 S2 Sector &amp; Regulation \u00b7 S3 Macroeconomic &amp; Markets")
    html = html.replace(
        "Run report now</a>",
        f'Run report now</a> &nbsp;&middot;&nbsp; <a href="{_ARCHIVE_URL}" '
        f'style="color:#888;text-decoration:underline;">Past editions</a>',
    )
    return html


def _from_display_name() -> str:
    """The name shown in the reader's From field, used for the subject
    line and attachment filename too.

    Was neutralised to "Daily News Digest" more than once suspecting a
    Defender impersonation block, most recently after a test send to
    careedge.in was accepted by our SMTP but appeared not to arrive --
    but that mail turned up later, just delayed in the relay/queue, not
    blocked. So the branding was never actually the problem; restored to
    "CareEdge Daily News" accordingly. If a future test looks like a
    block again, wait for late delivery before re-neutralising this --
    confirm an actual rejection (bounce, quarantine, message-trace
    "blocked") before assuming impersonation scoring, not just slow
    arrival.
    """
    return os.environ.get("MAIL_FROM_NAME", "CareEdge Daily News").strip() or "CareEdge Daily News"


def _admin_addr() -> str:
    """Where reader feedback and operational alerts should land.

    This was hardcoded to GMAIL_USER, which is now a mailbox Google has
    blocked — so every "not relevant?" and "Request an entity" link in the
    newsletter, and every delivery-failure alert, was pointing at a dead
    address. ADMIN_EMAIL overrides; otherwise fall back to the verified
    sender, and only then to the legacy Gmail name.
    """
    return (os.environ.get("ADMIN_EMAIL", "").strip()
            or os.environ.get("SMTP_FROM", "").strip()
            or os.environ.get("GMAIL_USER", "").strip())


def _smtp_settings() -> tuple[str, int, str, str, str]:
    """(host, port, user, password, from_address).

    Gmail was hardcoded here, and a free Gmail account doing automated bulk
    sending from a datacenter IP is exactly the pattern Google blocks —
    which is what happened. Host/port/credentials are now read from the
    environment so the desk can move to a corporate relay or a
    transactional provider by changing SECRETS ALONE, with no code change
    and no redeploy. Defaults preserve the previous Gmail behaviour.

    SMTP_FROM is separate from SMTP_USER because relays commonly
    authenticate as one identity and send as another (e.g. login as an
    API key, send as news@careedge.in).
    """
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER", "")
    pw = (os.environ.get("SMTP_PASSWORD")
          or os.environ.get("GMAIL_APP_PASSWORD", ""))
    frm = os.environ.get("SMTP_FROM") or user
    return host, port, user, pw, frm


_PDF_CACHE: dict = {}


def _html_to_pdf(html: str) -> bytes | None:
    """Render an edition to PDF bytes. None on ANY failure.

    Why PDF at all: Microsoft Defender's Common Attachment Types Filter
    blocks raw .html attachments outright as a credential-harvesting
    vector, and that policy is evaluated separately from sender
    allowlisting -- which is why whitelisting the sending domain never
    fixed careedge.in delivery. PDF is not on that blocked-type list.

    Fails open by design, like every other optional stage here: if
    WeasyPrint is missing or the render throws, the caller falls back to
    the old .html attachment rather than dropping the mail.

    Cached on the exact HTML, since recipients sharing the same sections
    generate byte-identical editions and rendering is ~1-10s each.
    """
    key = hash(html)
    if key in _PDF_CACHE:
        return _PDF_CACHE[key]
    try:
        import time as _t
        from weasyprint import HTML as _WeasyHTML
        # The S1/S2/S3 section wrapper (.news-page) forces a hard page
        # break before the next section, which is harmless in the email/
        # browser view (break-before is a print-only CSS property browsers
        # ignore on screen) but WeasyPrint treats everything as paginated
        # media. With a large S1 table (300+ rows -- this newsletter's
        # normal size now, not the handful of rows the 3-page layout was
        # designed around), S1 already overflows into dozens of pages on
        # its own; forcing S2 to start on a fresh page ON TOP of that
        # wastes most of whatever's left on S1's last page every time --
        # confirmed directly: one table row followed by a blank page.
        # Overriding to break-before:auto lets S1/S2/S3 flow straight into
        # each other -- the section banner is still there as a clear
        # visual break, it just doesn't force a wasted near-empty page.
        pdf_css = ("<style>.news-page{break-before:auto !important;"
                   "page-break-before:auto !important}</style>")
        pdf_html = html.replace("</head>", f"{pdf_css}</head>", 1)
        t0 = _t.time()
        pdf = _WeasyHTML(string=pdf_html).write_pdf()
        print(f"[pdf] rendered {len(pdf) // 1024} KB in {_t.time() - t0:.1f}s")
    except Exception as exc:
        print(f"[pdf] render failed (non-fatal, falling back to .html): {exc}")
        pdf = None
    _PDF_CACHE[key] = pdf
    return pdf


def _send_via_brevo_api(to_addr: str, subject: str, html: str,
                        attachment_html: str, attachment_name: str,
                        api_key: str, attachment_bytes: bytes | None = None) -> None:
    """Send over Brevo's HTTPS transactional API instead of SMTP.

    Brevo's "authorised IPs" security feature gates SMTP KEYS by source IP.
    GitHub Actions runners sit behind shared NAT and draw a different
    address every run, so there is no IP that can usefully be allowlisted —
    the result was a 525 'Unauthorized IP address' on every send even
    though the credentials were correct. The HTTPS API authenticates with
    an api-key header and is not subject to that SMTP gate, which makes
    this path immune to the whole class of problem.

    Body shape per Brevo's v3 send-transac-email reference: sender/to/
    subject/htmlContent, with attachments carrying base64 `content` and a
    `name` (the name is required whenever content is supplied, and the
    base64 must NOT include a data: URI prefix).
    """
    import base64
    import requests

    frm = (os.environ.get("SMTP_FROM")
           or os.environ.get("BREVO_FROM")
           or os.environ.get("GMAIL_USER", ""))
    payload = {
        "sender": {"name": _from_display_name(), "email": frm},
        "to": [{"email": to_addr}],
        "subject": subject,
        "htmlContent": html,
    }
    # Until the sending domain is authenticated, Brevo rewrites the From to
    # its own shared domain (…@…brevosend.com), so a reader hitting Reply
    # would write to an address nobody reads. Point replies at the desk.
    reply_to = _admin_addr()
    if reply_to and reply_to != frm:
        payload["replyTo"] = {"email": reply_to}
    if attachment_bytes:
        payload["attachment"] = [{
            "name": attachment_name,
            "content": base64.b64encode(attachment_bytes).decode("ascii"),
        }]
    elif attachment_html:
        payload["attachment"] = [{
            "name": attachment_name,
            "content": base64.b64encode(attachment_html.encode("utf-8")).decode("ascii"),
        }]
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "content-type": "application/json",
                 "accept": "application/json"},
        json=payload, timeout=60)
    if resp.status_code >= 300:
        # Surface Brevo's own message — its 4xx bodies name the exact
        # problem (unverified sender, bad key, quota), which is far more
        # actionable than a bare status code.
        raise RuntimeError(f"Brevo API {resp.status_code}: {resp.text[:300]}")


def _inline_full_edition(body_html: str, attachment_html: str) -> str:
    """Merges the full newspaper edition into the email body instead of
    sending it as a separate .html attachment.

    Reported: mail reliably reaches Gmail but not careedge.in, even after
    the sender display name, subject line, and domain were all fixed for
    the brand-impersonation signal -- ruling those out. What's left is
    the one thing that survives all of that: every mail carried a raw
    .html file attachment, which Defender for Office 365 (and most
    corporate mail security policies) routinely blocks or strips outright
    as a phishing/credential-harvesting vector, independent of sender
    reputation. Folding the same content into the body removes the
    attachment entirely rather than trying to make an .html attachment
    look safe enough to pass -- it's still a .html file either way.

    The top-5 quick-view email stays exactly as it is (simple, inline-
    styled, renders everywhere including Outlook's Word engine); the full
    multi-page edition's own <style> and body content are appended below
    it, not replacing it, so a reader gets both without needing a
    download.
    """
    style_m = re.search(r"<style>.*?</style>", attachment_html, re.S)
    body_m = re.search(r"<body[^>]*>(.*)</body>", attachment_html, re.S)
    if not style_m or not body_m:
        return body_html  # malformed attachment doc -- fail open, no crash
    style = style_m.group(0)
    inner = body_m.group(1)
    divider = ('<table width="100%" cellpadding="0" cellspacing="0">'
               '<tr><td style="padding:24px 0 4px;border-top:2px solid #1a1a1a;'
               'font-family:Arial,Helvetica,sans-serif;font-size:11px;'
               'font-weight:800;letter-spacing:2px;text-transform:uppercase;'
               'color:#1a1a1a;">Full Edition</td></tr></table>')
    return body_html.replace("</head>", f"{style}</head>", 1) \
                     .replace("</body>", f"{divider}{inner}</body>", 1)


def _send(to_addr: str, subject: str, html: str,
          attachment_html: str = "", attachment_name: str = "",
          attachment_bytes: bytes | None = None) -> None:
    # Preferred when configured: no SMTP, so no IP allowlist to trip over.
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if api_key:
        _send_via_brevo_api(to_addr, subject, html,
                            attachment_html, attachment_name, api_key,
                            attachment_bytes)
        print(f"[mail] sent '{subject}' -> {to_addr} (Brevo API)")
        return
    host, port, user, pw, frm = _smtp_settings()
    if attachment_bytes or attachment_html:
        msg = MIMEMultipart("mixed")
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(html, "html"))
        msg.attach(body)
        # application/pdf when we have a rendered PDF; text/html only as
        # the fall-back path when the PDF render failed.
        if attachment_bytes:
            part = MIMEBase("application", "pdf")
            part.set_payload(attachment_bytes)
        else:
            part = MIMEBase("text", "html")
            part.set_payload(attachment_html.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        msg.attach(part)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html"))
    msg["Subject"] = subject
    msg["From"] = f"{_from_display_name()} <{frm}>"
    msg["To"] = to_addr
    # Port 465 is implicit TLS (SMTP_SSL); 587 and 25 are plaintext-then-
    # STARTTLS, which is what every corporate relay and transactional
    # provider expects. Picking on port rather than a separate flag keeps
    # the configuration to one fewer secret.
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=60) as s:
            if pw:
                s.login(user, pw)
            s.sendmail(frm, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.ehlo()
            try:
                s.starttls()
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                # An internal relay on port 25 may accept unencrypted mail
                # from trusted hosts and offer no STARTTLS at all.
                pass
            if pw:
                s.login(user, pw)
            s.sendmail(frm, [to_addr], msg.as_string())
    print(f"[mail] sent '{subject}' -> {to_addr}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _mark_sent_today() -> None:
    path = os.path.join(_REPO_ROOT, "data", "team_last_sent.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = datetime.datetime.now(IST).date().isoformat()
    payload = json.dumps({"date": today})
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    _git_push(path, content=payload)


def main() -> None:
    team = _load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%A, %d %B %Y")

    # Scheduled runs respect the holiday calendar; manual dispatch always
    # sends. TEAM_SCHEDULED is hardcoded 'true' in the workflow's env for
    # EVERY run — schedule or manual — so it could never actually
    # distinguish them; a Saturday/Sunday test dispatch was silently
    # skipped despite being explicitly triggered, contradicting the very
    # message this block printed. GITHUB_EVENT_NAME is set automatically
    # by GitHub Actions on every run (no workflow-file change needed) and
    # is the real signal: 'schedule' for a cron tick, 'workflow_dispatch'
    # for a manual run.
    global _AI_ENABLED
    _AI_ENABLED = bool(team.get("use_ai", False))
    print(f"[ai] {'ENABLED' if _ai_on() else 'off'} — "
          f"{'AI classification, dedup review and mail-body writing active' if _ai_on() else 'mechanical rules only (team.json use_ai=false or no API key)'}")

    weekday = now.strftime("%A")
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        if team.get("skip_sundays", True) and weekday == "Sunday":
            print("[skip] Sunday — no mail (skip_sundays enabled; manual runs still work)")
            return
        # The desk works Mon-Fri. A Saturday edition went to 35 people who
        # were not reading it — dropped the same way Sunday already was.
        # Nothing from Saturday is lost: Monday's Weekend Edition below
        # widens its own lookback specifically to cover it.
        if team.get("skip_saturdays", True) and weekday == "Saturday":
            print("[skip] Saturday — no mail (skip_saturdays enabled; manual runs still work)")
            return
        if now.date().isoformat() in team.get("holidays", []):
            print(f"[skip] {now.date().isoformat()} is in the holiday list — no mail")
            return

    # Monday's edition is the first the desk sees since Friday — a normal
    # 48h lookback would silently drop Friday's own late news (already
    # stale by Monday) and everything published over the weekend, since no
    # mail (and no fetch) runs Sat/Sun. Reach back to Friday morning instead.
    is_weekend_edition = weekday == "Monday"
    lookback_days = 4 if is_weekend_edition else 2
    if is_weekend_edition:
        print("[weekend] Monday run — widening lookback to 4 days (Fri-Mon)")

    print("Fetching news (free sources)...")
    # apply_seen=False: do NOT inherit the daily Claude report's memory —
    # otherwise items that report published are hidden from team mails
    # forever even though the team mail never delivered them. The team
    # mailer relies solely on its own team_seen.json.
    # per_company_cap=25: effectively uncapped for S1 — Google rarely returns
    # more than ~20 fresh results for one entity's query, and the old cap of 5
    # let Google's ranking (which often puts chart noise and scheme pages on
    # top) crowd out genuine stories (a Kissht IPO item, SIDBI branch
    # expansion). The junk filter and cross-source dedup absorb the extra
    # volume; the 7:30 report keeps its own default of 3, untouched.
    # Query the console's entities, not watchlist.txt. That file holds the
    # 7:30 report's own 41 names, and it was the ONLY thing the per-entity
    # Google search ever ran on — so 332 of the desk's 370 entities could
    # not produce S1 news no matter what was published about them.
    wl_companies = sorted({r["company"].strip() for r in rows if r.get("company", "").strip()})
    # Per-entity short names typed into the console's "Aliases / Short
    # names" column. Each becomes its own quoted phrase in that entity's
    # Google query, which is the desk's own escape hatch for an entity the
    # press never refers to by its registered name.
    wl_aliases = _row_aliases(rows)
    n_alias = sum(len(v) for v in wl_aliases.values())
    print(f"[watchlist] querying {len(wl_companies)} entities from team.json "
          f"({n_alias} console alias(es) across {len(wl_aliases)} entities)")
    news_text, _summary = fetch_all_news(os.environ.get("NEWSAPI_KEY", ""),
                                         apply_seen=False, per_company_cap=25,
                                         companies=wl_companies, max_items=None,
                                         days_back=lookback_days,
                                         telegram_days_back=lookback_days,
                                         # 7:40 only. An entity's REGISTERED name is
                                         # often longer than the name the press uses
                                         # ("Alpha Alternatives Financial Services
                                         # Private Limited" is reported as "Alpha
                                         # Alternatives"), and the query is a quoted
                                         # exact phrase — so ~24% of the desk's
                                         # entities could never match their own
                                         # coverage. This ORs the shortened form in.
                                         # 7:30's query construction is unchanged.
                                         broad_company_queries=True,
                                         extra_aliases=wl_aliases)
    # The per-source counts were computed and then thrown away, so a source
    # collapsing to zero (as the watchlist fetch did for three days) was
    # invisible in the log.
    print("[sources] " + ", ".join(f"{k}={v}" for k, v in sorted((_summary or {}).items())))
    # Merge into the persistent pool so a run that Google under-serves does
    # not lose the day's coverage — see _merge_pool.
    fresh_lines = [ln for ln in news_text.splitlines() if ln.strip()]
    pooled_lines, pool_to_save, _new = _merge_pool(fresh_lines)
    items = [_parse_item(ln) for ln in pooled_lines]
    print(f"[sources] {len(items)} parsed items, "
          f"{sum(1 for it in items if it.get('wl_company'))} carry a WATCHLIST tag")

    seen = _load_seen()
    pre_seen = len(items)
    items = [it for it in items if not _is_already_sent(it, seen)]
    print(f"[dedup] {pre_seen - len(items)} items already sent on an earlier day "
          f"(exact match or same-story fingerprint)")
    print(f"{len(items)} items after team-mail dedup")

    pre_junk = len(items)
    dropped = [it for it in items if _is_team_junk(it)]
    items = [it for it in items if not _is_team_junk(it)]
    for it in dropped[:10]:
        print(f"[junk] dropped: {it['title'][:80]}")
    print(f"{len(items)} items after junk filter (dropped {pre_junk - len(items)})")

    pre_geo = len(items)
    off = [it for it in items if _is_out_of_scope(it)]
    items = [it for it in items if not _is_out_of_scope(it)]
    for it in off[:10]:
        print(f"[scope] dropped (not India): {it['title'][:75]}")
    print(f"{len(items)} items after geography filter (dropped {pre_geo - len(items)})")

    today_d = now.date()
    pre_stale = len(items)
    stale = [it for it in items if _is_stale(it, today_d, lookback_days)]
    items = [it for it in items if not _is_stale(it, today_d, lookback_days)]
    for it in stale[:8]:
        print(f"[stale] dropped (>48h old): [{it.get('pub')}] {it['title'][:70]}")
    n_stale = pre_stale - len(items)
    print(f"{len(items)} items after recency filter (dropped {n_stale})")

    phrases = [_phrase(r["company"]) for r in rows]
    sectors = _load_sectors(team)
    macro_kw = [str(k).strip().lower() for k in team.get("macro_keywords", []) if str(k).strip()]
    print(f"[sectors] {', '.join(f'{n}({len(k)}kw)' for n, k in sectors.items()) or 'none'}"
          f" | macro={len(macro_kw)}kw")
    # Match companies BEFORE dedup, not after: the classifier needs it, and
    # so does the same-entity merge below — without it, dedup can only see
    # the fetcher's tag and cannot tell that eight differently-worded
    # headlines are all about one company's quarterly results.
    for it in items:
        it["companies"] = _match_companies(it, rows)

    pre_dup = len(items)
    items = _dedup_cross_source(items)
    n_dup = pre_dup - len(items)
    print(f"{len(items)} items after cross-source dedup (merged {n_dup})")
    _classify_items_ai(items, phrases, sectors, macro_kw)
    for it in items:
        if it["section"] == "S2":
            it["sectors"] = _item_sectors(it, sectors)

    pre_stale_macro = len(items)
    stale_macro = [it for it in items
                   if it["section"] == "S3" and _is_stale_macro_period(it, today_d)]
    if stale_macro:
        stale_ids = {id(it) for it in stale_macro}
        items = [it for it in items if id(it) not in stale_ids]
        for it in stale_macro[:8]:
            print(f"[stale-macro] dropped (reference period >3 months old): {it['title'][:75]}")
        print(f"{len(items)} items after macro-period freshness filter "
              f"(dropped {pre_stale_macro - len(items)})")

    pre_offtopic = len(items)
    offtopic = [it for it in items if it["section"] is None]
    items = [it for it in items if it["section"] is not None]
    # Second AI pass on the survivors: catch entity matches that are wrong
    # and stories that repeat one already in the list. Fails open.
    items = _ai_review_items(items)
    for it in offtopic[:8]:
        print(f"[offtopic] dropped (no financial-sector signal): {it['title'][:75]}")
    # (I) False negatives are invisible by definition — the report cannot
    # show what it wrongly threw away. Keep the titles so the weekly review
    # can catch an over-tuned filter (a REIT funding story and an SDL
    # re-issue were both being discarded before this existed).
    dropped_samples = {
        "relevance": [it["title"][:110] for it in offtopic[:20]],
        "junk": [it["title"][:110] for it in dropped[:20]],
    }
    print(f"{len(items)} items after relevance filter (dropped {pre_offtopic - len(items)})")

    # Only the surviving pool needs real links — resolve after all filtering
    # so we never spend requests on items nobody will receive.
    _resolve_gnews_links(items)

    comp_counts: dict[str, int] = {}
    for it in items:
        for c in it["companies"]:
            comp_counts[c] = comp_counts.get(c, 0) + 1
        if it.get("wl_company") and not it["companies"]:
            print(f"[WARN] watchlist-tagged item matched no row: "
                  f"tag='{it['wl_company']}' title='{it['title'][:70]}'")
    print("Per-company matches:", comp_counts or "none")

    by_section: dict[str, list[dict]] = {s: [] for s in SECTION_TITLES}
    for it in items:
        by_section[it["section"]].append(it)
    print("Section counts:", {s: len(v) for s, v in by_section.items()})

    # Build per-person profile: email -> {name, companies(for S1), sections}
    # One-off manual test: restrict to a single recipient and/or section set
    # WITHOUT touching team.json (which would affect all 7 GHs). Set via
    # workflow_dispatch inputs -> TEST_EMAIL / TEST_SECTIONS env vars. Never
    # set on a scheduled run, so normal mornings are completely unaffected.
    # Comma/semicolon-separated so one manual run can cover several people
    # at once (e.g. "just the RHs and Punit, not the whole team again") —
    # without this a re-run to reach 4 people meant 4 queued workflow runs
    # back to back (same concurrency group), each redoing the full fetch.
    test_emails = {e.strip().lower() for e in re.split(r"[,;]", os.environ.get("TEST_EMAIL", ""))
                   if e.strip()}
    test_sections_env = os.environ.get("TEST_SECTIONS", "").strip()
    test_sections = {s.strip().upper() for s in test_sections_env.split(",") if s.strip()} or None
    if test_emails:
        print(f"[test] restricting this run to {', '.join(sorted(test_emails))}"
              f"{' / sections ' + ','.join(sorted(test_sections)) if test_sections else ''}")

    people: dict[str, dict] = {}
    for r in rows:
        # Legacy rows tick S4/S5; both now live in S3. Deliberately NOT
        # _TEAM_SECTION_MAP — that maps classifier output, where "S3" still
        # means the old regulation bucket. Re-mapping row ticks with it would
        # rewrite a new-scheme S3 (macro) subscription to S2 on every load.
        for name_f, email_f, send_f, sections_f in ROLES:
            # Per-role sections, falling back to the legacy shared "sections"
            # field for rows not yet migrated to per-role fields.
            secs = {_ROW_SECTION_MIGRATE.get(x, x)
                    for x in r.get(sections_f, r.get("sections", []))}
            if test_sections is not None:
                secs = secs & test_sections
            # In test mode, match by email regardless of the row's Send tick
            # — a manual test should not depend on that row happening to be
            # enabled. Normal runs keep the send_f gate exactly as before.
            if not test_emails and not r.get(send_f):
                continue
            # A cell may hold several addresses ("a@x, b@x; c@x") — each
            # address gets its own personalized mail.
            for email in (e.strip() for e in re.split(r"[,;]", r.get(email_f, "")) if e.strip()):
                if test_emails and email.strip().lower() not in test_emails:
                    continue
                if not secs:
                    continue
                p = people.setdefault(email, {
                    "name": r.get(name_f, "").strip() or email.split("@")[0],
                    "companies": set(), "sections": set(), "sectors": set(),
                })
                p["sections"].update(secs)
                p["sectors"].add(_row_sector(r))
                if "S1" in secs:
                    p["companies"].add(r["company"])

    if test_emails:
        # A test address typed into the console (e.g. a personal Gmail for
        # checking delivery) usually isn't in any team.json row at all, so
        # the match loop above never adds it — that used to mean "nobody
        # enabled" and the whole run quietly sent nothing. Give any
        # still-unmatched test address the master edition (every company,
        # every section) instead of just dropping it, so a test send always
        # produces mail regardless of whether that address is on the team.
        matched = {e.strip().lower() for e in people}
        for addr in test_emails - matched:
            secs = {"S1", "S2", "S3"} & (test_sections or {"S1", "S2", "S3"})
            if not secs:
                continue
            people[addr] = {
                "name": "",
                "companies": {r["company"] for r in rows},
                "sections": secs,
                "sectors": set(sectors) | {_row_sector(r) for r in rows},
            }

    if not people:
        print("[route] nobody is enabled in team.json — no mails to send")
        _save_seen(items)
        return

    # Lazy import: send_credit_report imports helpers from this module at its
    # top level, so importing it here (after this module is fully loaded) is
    # safe, while a module-level import would be circular.
    import send_credit_report as _scr

    today = now.date()
    masthead = "CareEdge Weekend Edition" if is_weekend_edition else "CareEdge Daily News"
    coverage_note = "Covering Fri–Mon" if is_weekend_edition else ""

    # Credit lens: the TOP 3-5 S2 stories and TOP 3-5 S3 stories, desk-wide
    # (not per person — the same regulatory action is everyone's top story),
    # get a one-line "why a credit analyst cares" note attached to their
    # card. Computed BEFORE the part-B pass below so every reader's
    # attachment can carry it. Fails open to no lens line, same as every
    # other AI-assisted feature here.
    section_takeaways: dict = {}
    if _ai_on():
        s2_top = _rating_first(by_section.get("S2", []))[:5]
        s3_top = _rating_first(by_section.get("S3", []))[:5]
        lens_candidates = s2_top + s3_top
        if lens_candidates:
            try:
                import anthropic
                _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""), timeout=60, max_retries=1)
                section_takeaways = _ai_takeaway_batch(lens_candidates, _client)
                print(f"[ai_takeaway] {len(section_takeaways)}/{len(lens_candidates)} "
                      f"desk-wide S2/S3 key stories got a credit lens")
            except Exception as exc:
                print(f"[ai_takeaway] desk-wide pass unavailable (non-fatal): {exc}")

        # S1 table Summary column: every watchlist item gets a real
        # analytical view, not just a headline restated. Computed once
        # desk-wide (an item shared by several GHs gets one view, not a
        # separate AI call per reader) and merged into the same dict the
        # S2/S3 lens uses -- _np_s1_row looks it up by the same item key.
        s1_items = by_section.get("S1", [])
        if s1_items:
            try:
                import anthropic
                _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""), timeout=60, max_retries=1)
                for start in range(0, len(s1_items), _TAKEAWAY_BATCH_SIZE):
                    batch = s1_items[start:start + _TAKEAWAY_BATCH_SIZE]
                    section_takeaways.update(_ai_s1_view_batch(batch, _client))
                print(f"[ai_s1_view] {sum(1 for it in s1_items if _key(it) in section_takeaways)}"
                      f"/{len(s1_items)} S1 items got an analytical view")
            except Exception as exc:
                print(f"[ai_s1_view] desk-wide pass unavailable (non-fatal): {exc}")

    # GPT (Gemini/OpenAI) credit analysis -- S1 Summary, S2/S3 Credit lens,
    # and email body. Runs independently of _ai_on()/ANTHROPIC_API_KEY
    # (separate provider, separate on/off switch) and, if it succeeds, its
    # entries OVERRIDE the Anthropic/mechanical ones in section_takeaways
    # above -- same insertion point for all three sections, so _np_partb/
    # _np_s1_row/_np_card need no changes. Any failure (no key, API error,
    # malformed response) leaves section_takeaways exactly as the existing
    # pipeline already built it -- nothing here can make a section worse
    # than before. S2/S3 previously only got a Credit lens line for the
    # top-3 hero items per section (Anthropic path); GPT's coverage isn't
    # gated by hero status -- see the _np_partb S2/S3 branch below.
    gpt_exec_summary, gpt_watchlist_html = "", ""
    gpt_excluded: set = set()
    gpt_s1_items = by_section.get("S1", [])
    if gpt_s1_items:
        gpt_result = _gpt_analysis(gpt_s1_items, by_section.get("S2", []),
                                    by_section.get("S3", []), today)
        if gpt_result:
            gpt_data, gpt_s1_sent, gpt_s2_sent, gpt_s3_sent = gpt_result
            gpt_s1_map = _gpt_map_s1(gpt_data, gpt_s1_sent)
            gpt_s2_map = _gpt_map_cat(gpt_data, "s2_summary", gpt_s2_sent)
            gpt_s3_map = _gpt_map_cat(gpt_data, "s3_summary", gpt_s3_sent)
            section_takeaways.update(gpt_s1_map)
            section_takeaways.update(gpt_s2_map)
            section_takeaways.update(gpt_s3_map)
            # An item GPT was actually shown but left OUT of s2_summary/
            # s3_summary was judged, not just skipped -- "let Gemini also
            # filter S2/S3" means that judgment should drop the row, not
            # just leave it with no analysis line. Items beyond the
            # per-run cap were never shown to GPT at all and must not be
            # swept into this set -- they stay in the table with the
            # mechanical fallback exactly as before.
            gpt_excluded = ({_key(it) for it in gpt_s2_sent} - set(gpt_s2_map)) | \
                           ({_key(it) for it in gpt_s3_sent} - set(gpt_s3_map))
            gpt_exec_summary, gpt_watchlist_html = _gpt_map_email_body(gpt_data)
            print(f"[gpt] {len(gpt_s1_map)}/{len(gpt_s1_sent)} S1 items, "
                  f"{len(gpt_s2_map)}/{len(gpt_s2_sent)} S2 items, "
                  f"{len(gpt_s3_map)}/{len(gpt_s3_sent)} S3 items carry a "
                  f"GPT credit view ({len(gpt_excluded)} S2/S3 items filtered "
                  f"out as not material); email body "
                  f"{'set' if gpt_exec_summary else 'not set'} from GPT")

    # First pass: build everyone's part B / Top-5 with no per-person AI call
    # involved (cheap, deterministic — section_takeaways above is the one
    # shared AI pass this needs). This has to happen before the AI mail-body
    # pass below so it can batch ONE call across every recipient's Top-5
    # instead of a separate AI round-trip per person in the send loop.
    prepared: dict = {}
    for email, p in people.items():
        part_b, total, person_items = _np_partb(p, items, by_section, section_takeaways, gpt_excluded)
        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[mail] skipping {email} — nothing new in their sections")
            continue
        # Top 10, S1 first: the email-body "quick view" should prioritise
        # the reader's own watchlist over shared sector/macro news. All S1
        # items are ranked ahead of any S2/S3 item regardless of score;
        # S2/S3 only fills remaining slots when S1 doesn't have 10 items
        # on its own.
        s1_ranked = sorted((it for it in person_items if it.get("section") == "S1"),
                            key=_story_score, reverse=True)
        other_ranked = sorted((it for it in person_items if it.get("section") != "S1"),
                               key=_story_score, reverse=True)
        top5 = (s1_ranked + other_ranked)[:10]
        prepared[email] = {
            "name": (p.get("name") or "").strip(),
            "part_b": part_b, "top5": top5,
            "sections": set(p.get("sections") or ()),
            "digest": _mech_digest(person_items, len(p.get("companies") or [])),
        }

    takeaways, summaries = _ai_mail_body_content(
        {email: (v["name"], v["top5"]) for email, v in prepared.items()})
    # section_takeaways is {item_key: str} from the Anthropic per-item pass
    # OR {item_key: {"variable", "implication", "why", "commentary", ...}}
    # from the GPT/Gemini S1 mapping -- _np_partc's why-line wants a plain
    # string either way. Coerce dict values to their "commentary" text so a
    # GPT-only run (Anthropic pass empty/failed, e.g. out of credits) never
    # leaks a raw dict repr into the email body.
    # NOTE: these are two DIFFERENT shapes for two different consumers --
    # keep them separate. _np_partc (email body) wants plain strings;
    # _np_partb/_np_s1_row (the S1/S2/S3 tables) want the dict form and
    # call view.get("commentary") on it. Merging both into one variable is
    # what caused the raw-dict leak in the body AND, once flattened, an
    # AttributeError in the master-edition table build.
    section_takeaways_str = {
        k: (v.get("commentary", "") if isinstance(v, dict) else v)
        for k, v in section_takeaways.items()
    }
    email_takeaways = {**section_takeaways_str, **takeaways}

    sent_count, failed = 0, []
    for email, v in prepared.items():
        who, part_b, top5 = v["name"], v["part_b"], v["top5"]
        # Per explicit instruction: the email body stays JUST the Top 10
        # Headlines list (S1 first, then S2/S3 filling remaining slots) for
        # now -- gpt_exec_summary/gpt_watchlist_html are computed above
        # (and logged) but deliberately not rendered here yet. GPT's S1
        # analysis still lands in the S1 Summary table via
        # section_takeaways, unaffected by this.
        blurb = summaries.get(email, "") or v["digest"]
        part_c = _np_partc(top5, now.strftime("%d %B %Y"), email_takeaways, blurb)
        body = _np_rebrand(_scr.build_email(part_c, today, _summary))
        attachment = _np_rebrand(_np_build_attachment(
            part_b, today, who, masthead, coverage_note, v["sections"]))
        # Each edition is built from that reader's own entities, so name it.
        # Uses the neutral MAIL_FROM_NAME, not the "CareEdge Daily News"
        # masthead: the subject is the one thing every spam/anti-phish
        # filter reads regardless of display-name/sender fixes, and
        # "CareEdge" in the subject from an unrelated mailalerts.in domain
        # is the same brand-impersonation signal that got the From name
        # changed earlier -- reported still blocking delivery on the
        # careedge.in side even after IT allowlisted the domain. The
        # newsletter's own masthead/branding inside the mail is untouched.
        subj_name = _from_display_name()
        subject = (f"{subj_name} — {who} — {now:%d %b %Y}" if who
                   else f"{subj_name} — {now:%d %b %Y}")
        # Confirmed by test (2026-08-20): removing the .html attachment
        # fixed delivery to careedge.in -- everything else (From name,
        # subject, domain whitelist) was already correct. Reinstating the
        # attachment anyway per explicit instruction, accepting that the
        # careedge.in block will likely return. _inline_full_edition()
        # is kept in the file, unused, as the known-working fallback if
        # this needs reverting again.
        # One bad mailbox must not stop the rest of the team's mails.
        try:
            # Attachment filename uses the same neutral name as the From
            # display name and subject -- "CareEdge" in the filename is
            # the same brand-vs-unrelated-domain signal already fixed
            # elsewhere.
            attach_name = _from_display_name().replace(" ", "_")
            # PDF, not .html: Defender blocks .html attachments by
            # attachment-type policy regardless of sender allowlisting
            # (confirmed -- whitelisting the domain never fixed
            # careedge.in). Falls back to the original .html attachment
            # if the renderer is unavailable, so this can only improve
            # deliverability, never stop a send.
            pdf = _html_to_pdf(attachment)
            if pdf:
                _send(email, subject, body,
                      attachment_bytes=pdf,
                      attachment_name=f"{attach_name}_{today:%Y%m%d}.pdf")
            else:
                _send(email, subject, body,
                      attachment_html=attachment,
                      attachment_name=f"{attach_name}_{today:%Y%m%d}.html")
            sent_count += 1
        except Exception as exc:
            print(f"[mail] FAILED for {email}: {exc}")
            failed.append(email)

    if failed:
        print(f"[mail] {len(failed)} failed: {', '.join(failed)}")
        admin = _admin_addr()
        if admin:
            try:
                _send(admin, "CareEdge Daily News — delivery failures",
                      "<p>Delivery failed for:</p><ul>" +
                      "".join(f"<li>{e}</li>" for e in failed) +
                      f'</ul><p><a href="{_MANAGE_URL}">Check addresses in the console</a></p>')
            except Exception:
                pass

    if not test_emails:
        try:
            status_rows = "".join(
                f'<li>{len(people.get(e, {}).get("companies") or [])} co(s), '
                f'sections {",".join(sorted(v["sections"]))}: '
                f'<b style="color:{("#cc0000" if e in failed else "#2E6B4F")}">'
                f'{"FAILED" if e in failed else "sent"}</b> — {e}</li>'
                for e, v in prepared.items())
            failed_clause = (f', <b style="color:#cc0000">{len(failed)} failed</b>'
                              if failed else "")
            _send(_STATUS_EMAIL, f"7:40 Team Mail status — {now:%d %b %Y}",
                  f"<p><b>{sent_count} sent</b>{failed_clause}"
                  f" out of {len(prepared)} recipients.</p>"
                  f"<p>Run time: {now:%d %b %Y %H:%M} IST.</p>"
                  f'<ul style="font-size:12px">{status_rows}</ul>'
                  f'<p><a href="{_MANAGE_URL}">Console</a></p>')
        except Exception as exc:
            print(f"[status] status mail failed (non-fatal): {exc}")

    # Master edition (all companies, all sections) for the public archive.
    master_p = {"sections": {"S1", "S2", "S3"},
                "companies": {r["company"] for r in rows},
                "sectors": set(sectors) | {_row_sector(r) for r in rows}}
    m_partb, _m_total, _m_items = _np_partb(master_p, items, by_section, section_takeaways, gpt_excluded)
    _write_archive(_np_rebrand(_np_build_attachment(m_partb, today, "", masthead, coverage_note)), today)

    _append_stats({
        "date": today.isoformat(),
        "fetched": pre_junk,
        "delivered_pool": len(items),
        "junk": pre_junk - pre_geo, "geo": pre_geo - pre_stale,
        "stale": n_stale, "dup": n_dup,
        "sections": {s: len(v) for s, v in by_section.items()},
        "mails": sent_count, "failed": failed,
        "source_summary": {k: v for k, v in (_summary or {}).items() if not k.startswith("__")},
        "dropped_samples": dropped_samples,
    })
    if now.strftime("%A") == "Saturday":
        _send_weekly_stats(now)

    if test_emails:
        # A one-off test must not mark today as sent (that would block
        # tomorrow's real scheduled run) or teach the shared seen-memory
        # about items other GHs haven't received yet. The pool is skipped
        # too, so a test leaves no trace at all.
        print("[test] skipping seen-memory save, pool save and sent-today marker")
    else:
        _save_seen(items)
        # Saved even though the mail is out: tomorrow's run inherits today's
        # fetched lines, so coverage accumulates rather than depending on
        # whatever a single Google search happened to return.
        try:
            _save_pool(pool_to_save)
        except Exception as exc:
            print(f"[pool] save failed (non-fatal): {exc}")
        _mark_sent_today()
    print("Done.")


if __name__ == "__main__":
    main()
