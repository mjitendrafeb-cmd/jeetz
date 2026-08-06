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

# Mechanical version of the 7:30 report's AI SKIP rules (stock tips, target
# price calls, awards, CSR, consumer product launches). Same intent, no AI.
_TEAM_JUNK_RE = re.compile(
    r"\b(buy|sell|hold|accumulate|reduce|add|neutral|not rated)\b[^.|]{0,70}\btarget\b"
    r"|\bfor the target\b"
    r"|\btarget (price|rs\.?)\b"
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
    r"|\b52[- ]week (high|low)\b"
    r"|\bsubscribe\b.{0,60}\bipo\b|\bipo\b.{0,60}\bsubscribe\b"
    r"|\b(gmp|grey market premium)\b"
    # Mutual-fund scheme/NAV pages — matched S4 on 'gilt' but carry no news
    # ("Kotak Gilt Investment Regular-IDCW Quarterly - NAV, Reviews...").
    r"|\bnav\b.{0,40}\b(review|asset allocation|scheme|portfolio)\b"
    r"|\b(idcw|direct plan|regular plan)\b"
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
    r"[^.|]{0,60}\b(sees?|expects?|estimates?|forecasts?|projects?|pegs?)\b",
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
    r"|\bcause list\b",
    re.IGNORECASE,
)

# Sources that never carry credit-relevant news for this desk, whatever the
# headline says: dedicated stock-tip feeds, HR/headcount data scrapers
# (reveliolabs "Auxilo Finserve Number of Employees 2026"), and crypto sites.
_JUNK_SOURCE_RE = re.compile(
    r"(@brokerage_report|reveliolabs|bitcoinworld|coindesk|cointelegraph|"
    r"zippia|growjo|leadiq|craft\.co|owler|rocketreach)",
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
    r"|\bhere'?s (what|how|why) you (need to know|should know)\b",
    re.IGNORECASE,
)


# Same rule as fetch_news._STOCK_MOVE_RE, kept here because the team mailer
# also sees items that did not come through that path.
_TEAM_STOCK_MOVE_RE = re.compile(
    r"\b(shares?|stock|share price|scrip|m-?cap)\b[^.|]{0,40}?\b"
    r"(jump|rall(y|ies|ied)|surg|soar|zoom|spike|climb|gain|rise|rises|risen|"
    r"advanc|drop|fall|fell|slip|slid|declin|tank|plunge|crash|slump|tumbl|"
    r"sink|sank|dip)\w*"
    r"|\b(jump|rall(y|ies)|surg|soar|zoom|spike|climb|gain|drop|fall|slip|"
    r"declin|tank|plunge|crash|slump|tumbl)\w*\b[^.|]{0,25}\b(shares?|stock|share price)\b"
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
    r"\b(rbi|sebi|irdai|nhb|pfrda|ibbi|nclt)\b[^.|]{0,45}?\b"
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
    r"box office|bollywood|tollywood|film|movie|web series|streaming (show|series)|"
    r"celebrity|actor|actress|singer|award (show|night)|reality show)\b",
    re.IGNORECASE,
)

# Tier 1 — a financial-sector signal. REQUIRED for anything to land in S2.
# Deliberately excludes bare corporate-action words: an acquisition or a
# Q1 result is only S2 news when the subject is a financial institution.
_FI_SIGNAL_RE = re.compile(
    r"\b(nbfc|hfc|housing finance|non-?banking financial|bank(s|ing)?|"
    r"microfinance|\bmfi\b|fintech|broking|brokerage|stock broker|"
    r"insurer|insuranc\w*|irdai|mutual fund|\bamc\b|asset management|"
    r"asset reconstruction|\barc\b|debenture trustee|chit fund|"
    r"small finance bank|payments? bank|cooperative bank|co-operative bank|"
    r"\brbi\b|\bsebi\b|\bnhb\b|nabard|sidbi|pfrda|\bibbi\b|"
    r"financial (services|institution)|finance (company|limited|ltd)|\bfinance\b|"
    r"lender[s]?|\bnpa\b|non-performing|gross npa|net npa|"
    r"credit (rating|profile|quality|growth|cost)|capital adequacy|provisioning|"
    r"disbursement|\baum\b|assets under management|securitisation|securitization|"
    r"net interest margin|\bnim\b|gold loan|vehicle loan|personal loan|"
    r"microcredit|priority sector)\b",
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
    r"\b(nbfc|hfc|housing finance|non-?banking financial|bank(s|ing)?|"
    r"microfinance|\bmfi\b|fintech|broking|brokerage|insurer|insuranc\w*|irdai|"
    r"mutual fund|\bamc\b|asset management|asset reconstruction|"
    r"small finance bank|payments? bank|cooperative bank|co-operative bank|"
    r"\brbi\b|\bsebi\b|\bnhb\b|nabard|sidbi|pfrda|\bibbi\b|"
    r"financial (services|institution))\b",
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

ROLES = (("gh_name", "gh_email", "send_gh"),
         ("analyst_name", "analyst_email", "send_analyst"),
         ("rh_name", "rh_email", "send_rh"))


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
    words = name.lower().split()
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
           "development", "investment", "securities", "insurance", "mutual", "fund"}


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


def _acronym(name: str) -> str:
    """SIDBI-style initialism from the name's non-filler words — real
    headlines say 'SIDBI', not 'Small Industries Development Bank'."""
    letters = [w[0] for w in name.lower().split()
               if w.strip(".,()") and w not in _FILLER and not w.startswith("(")]
    a = "".join(letters)
    return a if len(a) >= 4 else ""


def _mentions_company(body: str, name: str) -> bool:
    """Does the story text actually refer to this company? True when it
    contains the acronym (sidbi), any DISTINCTIVE name word (indostar,
    baroda, equitas), or at least TWO common words ('small' + 'industries').
    A single common word like 'small' is not enough — that attached
    Equitas Small Finance stories to SIDBI."""
    acro = _acronym(name)
    if acro and re.search(r"\b" + re.escape(acro) + r"\b", body):
        return True
    words = _sig_words(name)
    matched = [w for w in words if w in body]
    if any(w not in _COMMON for w in matched):
        return True
    return len(matched) >= 2


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
        m2 = re.match(r"WATCHLIST\s*[—-]\s*(.+)", t)
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
        return "S1"
    text = f'{it["tags"]} {it["source"]} {it["title"]} {it["summary"]}'.lower()
    # Sport, entertainment and stray CRA press pages are never rescued by a
    # keyword — those drops are absolute.
    if _NEVER_RELEVANT_RE.search(text) or _is_cra_announcement(it):
        return None
    if _kw_hit(text, macro_kw):
        return "S3"
    # A sector's keywords define what is relevant FOR THAT SECTOR. Checked
    # before deferring to `base`, because the built-in relevance gate is
    # BFSI-specific: it requires a bank/NBFC/RBI signal, so genuine news for
    # any other sector ("Road EPC order inflows surge as NHAI awards HAM
    # projects") would otherwise be discarded as having no financial signal
    # before the sector logic ever saw it.
    if sectors and any(_kw_hit(text, kws) for kws in sectors.values()):
        return "S2"
    if base is None:
        return None
    return _TEAM_SECTION_MAP.get(base)


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


def _match_companies(it: dict, rows: list[dict]) -> list[str]:
    """Tag from the fetcher is authoritative (the item came from that
    company's own query); text phrase match is only a fallback. Re-matching
    by text alone silently dropped tagged items whose headline did not
    repeat the company name."""
    body = (it["title"] + " " + it["summary"]).lower()
    tag = it.get("wl_company", "").lower()
    hits = []
    for r in rows:
        name = r["company"].strip()
        if not name:
            continue
        n = name.lower()
        tag_match = tag and (tag == n or tag.startswith(n) or n.startswith(tag))
        if tag_match:
            # Sanity: the story must actually mention the company. Google's
            # per-company query sometimes returns unrelated stories (e.g. a
            # Patanjali deal from 'D. S. Integrated's query because 'd.' is
            # a substring of every 'Ltd.').
            if _sig_words(name) and not _mentions_company(body, name):
                print(f"[WARN] tag '{name[:40]}' but story never mentions it: "
                      f"'{it['title'][:60]}' — dropped from this company")
                tag_match = False
        if tag_match or _contains_name(body, n) or _contains_name(body, _phrase(name)):
            hits.append(name)
    return hits


# ---------------------------------------------------------------------------
# Dedup memory (30-day, independent of the Claude report's memory)
# ---------------------------------------------------------------------------

def _key(it: dict) -> str:
    return f"{it['source']}: {it['title']}".lower().strip()[:120]


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
    days[str(datetime.date.today())] = [_key(it) for it in items]
    cutoff = str(datetime.date.today() - datetime.timedelta(days=30))
    days = {d: v for d, v in days.items() if d >= cutoff}
    with open(_SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, indent=2)
    _git_push(_SEEN_PATH)


def _git_push(path: str) -> None:
    try:
        import subprocess
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            subprocess.run(["git", "remote", "set-url", "origin",
                            f"https://x-access-token:{token}@github.com/mjitendrafeb-cmd/jeetz.git"],
                           cwd=_REPO_ROOT, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
                       cwd=_REPO_ROOT, capture_output=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"],
                       cwd=_REPO_ROOT, capture_output=True)
        subprocess.run(["git", "add", path], cwd=_REPO_ROOT, capture_output=True)
        r = subprocess.run(["git", "commit", "-m", "chore: update team news memory"],
                           cwd=_REPO_ROOT, capture_output=True)
        if r.returncode == 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=_REPO_ROOT, capture_output=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=_REPO_ROOT, capture_output=True)
    except Exception as exc:
        print(f"[git] non-fatal: {exc}")


# ---------------------------------------------------------------------------
# HTML rendering (plain, no AI) -- table-based layout for email-client
# compatibility (Outlook/Gmail), cream/navy palette.
# ---------------------------------------------------------------------------

_NAVY = "#132A46"
_NAVY_SOFT = "#9AA9BC"
_CREAM = "#EDEAE3"
_RED = "#A32638"
_GREEN = "#2E6B4F"
_GREY = "#8A8578"
_DIVIDER = "#ECE8E0"
_MANAGE_URL = "https://mjitendrafeb-cmd.github.io/jeetz/team.html"

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
        r"reaffirm\w*|withdraws? rating|assigns? [^.|]{0,25}rating)", re.IGNORECASE)),
    ("REGULATORY", "REGULATORY", 8, "#b45309", re.compile(
        r"\b(monetary penalty|imposes? (a )?penalt|penalis|penaliz|enforcement action|"
        r"adjudication order|show cause notice|debarr|cease and desist|sebi order|"
        r"compounding order|licence (cancel|revok)|registration cancel)", re.IGNORECASE)),
    ("MANAGEMENT", "MANAGEMENT", 7, "#7c3aed", re.compile(
        r"\b((ceo|cfo|md|managing director|chairman|auditor|director)[^.|]{0,30}"
        r"(resign|steps? down|quits?|exits?|appoint|elevat)|"
        r"(resign|steps? down|quits?)[^.|]{0,25}(ceo|cfo|md|chairman|auditor)|"
        r"auditor (resign|change)|board (approves|appoints))", re.IGNORECASE)),
    ("FUNDING", "FUNDING", 6, "#1e3a8a", re.compile(
        r"\b(raises?\s+(rs\.?\s?)?[\d.,]+\s*(crore|cr\b|million|billion)|"
        r"fund ?rais\w*|funding round|series [a-f]\b|\bqip\b|rights issue|"
        r"preferential allotment|capital infusion|tier[- ]?(i|ii|1|2) bonds?|"
        r"issues? (ncds?|debentures?|bonds?)|capital raise)", re.IGNORECASE)),
    ("M&A", "M&amp;A", 6, "#0f766e", re.compile(
        r"\b(acqui(re|res|red|sition)|merger|amalgamat\w*|stake (sale|buy|purchase|acquisition)|"
        r"divest\w*|takeover|open offer|slump sale)", re.IGNORECASE)),
    ("RESULTS", "RESULTS", 4, "#525252", re.compile(
        r"\b(q[1-4]\s?(fy)?\d*|quarterly|net profit|\bpat\b|\bnii\b|"
        r"net interest income|earnings|results?\b|gross npa|net npa)", re.IGNORECASE)),
]


def _event_of(it: dict) -> tuple[str, str, int, str]:
    """(key, label, score, colour). Highest-materiality match wins."""
    text = f'{it.get("title","")} {it.get("summary","")}'
    for key, label, score, colour, rx in _EVENTS:
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


def _resolve_gnews_url(url: str, title: str) -> str:
    """Return the publisher's article URL, or a Google News search link."""
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
    return _gnews_search_url(title)


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


def _dedup_cross_source(items: list[dict]) -> list[dict]:
    """7:30 rule, mechanical version: same story from several sources keeps
    ONE card (highest tier wins) with 'Also reported by: ...' under it.
    Watchlist items tagged to different companies are never merged."""
    kept: list[dict] = []
    for it in items:
        toks = _title_toks(it["title"])
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
            # A pure overlap ratio fails in both directions: three genuine
            # paraphrases of the RBI MPC story scored 0.54-0.70 and stayed
            # separate, while "HDFC Bank reports Q1 profit rise" vs "ICICI
            # Bank reports Q1 profit rise" scored 0.80 and would have merged
            # two different issuers. Require a real mass of shared words AND
            # the same leading subject, then the ratio can be loosened.
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
            it["_toks"], it["_lead"], it["_nkey"] = toks, lead, nkey
            kept.append(it)
        elif _tier_rank(it) < _tier_rank(winner):
            # newcomer is higher-tier: it replaces the kept item in place
            it["also"] = winner["also"] + [winner["source"]]
            it["_toks"], it["_lead"], it["_nkey"] = toks, lead, nkey
            kept[kept.index(winner)] = it
        else:
            if it["source"] not in winner["also"] and it["source"] != winner["source"]:
                winner["also"].append(it["source"])
    for k in kept:
        for tmp in ("_toks", "_lead", "_nkey"):
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
    admin = os.environ.get("GMAIL_USER", "")
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


def _np_card(it: dict, hero: bool = False, company: str = "") -> str:
    cls = "art hero" if hero else "art"
    bits = [_esc(b) for b in (company.upper() if company else "",
                              it["source"], it.get("pub", "")) if b]
    link = (f'<a class="rm" href="{_esc(it["url"])}" target="_blank">Read more &#8594;</a>'
            if it["url"] else "")
    fb = _feedback_link(it)
    also = (f'<br><span class="also">Also reported by: '
            f'{_esc(", ".join(it["also"]))}</span>' if it.get("also") else "")
    # No filler line when a feed gives no description — just omit it.
    summary = _esc(it["summary"])
    body = f'<p class="wh">{summary}</p>' if summary else ""
    return (f'<div class="{cls}"><p class="src">{" &bull; ".join(bits)}{_undated_note(it)}</p>'
            f'<p class="hl">{_esc(it["title"])}</p>'
            f'{body}{link}{fb}{also}</div>')


def _feedback_link(it: dict) -> str:
    """(J) One click to flag an item as irrelevant. A mailto keeps this
    working with no server, no endpoint and no auth — the reply lands in the
    admin mailbox with the exact title, which goes straight into
    suppress.json."""
    import urllib.parse
    admin = os.environ.get("GMAIL_USER", "")
    if not admin:
        return ""
    subj = urllib.parse.quote(f"[not relevant] {it.get('title','')[:120]}")
    return (f'<a href="mailto:{admin}?subject={subj}" '
            f'style="font-size:8px;color:#c9c4b8;text-decoration:none;'
            f'margin-left:8px;">not relevant?</a>')


def _company_header(name: str, its: list[dict]) -> str:
    """Entity sub-header inside S1. Styled inline rather than with a class,
    because the newspaper stylesheet lives in send_credit_report.py and the
    7:30 report is not to be modified."""
    n = len(its)
    top = max(_materiality(i) for i in its)
    # Flag the entity itself when it carries something that needs action.
    flag = ('<span style="color:#b91c1c;font-weight:800;"> &#9679; ACTION</span>'
            if top >= 8 else "")
    return (f'<p style="margin:14px 0 5px;font-size:10px;font-weight:800;'
            f'letter-spacing:1.2px;text-transform:uppercase;color:#111;'
            f'border-bottom:1px solid #bbb;padding-bottom:3px;'
            f'break-inside:avoid;">{_esc(name)}{flag}'
            f'<span style="color:#999;font-weight:600;"> &middot; {n} item'
            f'{"s" if n != 1 else ""}</span></p>')


def _np_partb(p: dict, items: list[dict], by_section: dict) -> tuple[str, int, list[dict]]:
    """Per-person Part B in the 7:30 class markup. Returns (html, story_count,
    the stories shown — used to pick the Top 5)."""
    parts: list[str] = []
    chosen: list[dict] = []
    total = 0
    for sid, sbcls, skey, title in _NP_SECTIONS:
        parts.append(f'<div id="{sid}" data-section="banner" class="sb {sbcls}">{title}</div>')
        if skey not in p["sections"]:
            parts.append('<p class="empty">Not subscribed &mdash; enable this section in the console.</p>')
            continue
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
            lead = True
            for comp, its in order:
                parts.append(_company_header(comp, its))
                for it in its:
                    parts.append(_np_card(it, hero=lead))
                    lead = False
        else:
            sec_items = by_section[skey]
            if skey == "S2" and p.get("sectors"):
                # A GH sees the sector(s) their own entities sit in.
                sec_items = [it for it in sec_items
                             if (it.get("sectors") or {_DEFAULT_SECTOR}) & p["sectors"]]
            if not sec_items:
                parts.append('<p class="empty">No news in this category today.</p>')
                continue
            total += len(sec_items)
            chosen.extend(sec_items)
            # Every story gets the same full-card treatment. The old 6-card
            # cut mirrored the 7:30 prompt, but there the AI *chooses* the six
            # most credit-significant stories -- with no AI the cut was
            # arbitrary, so genuinely material items (a CRISIL credit-ratio
            # story) were demoted to one-liners purely by fetch order. The old
            # [:20] slice also dropped everything past 20 outright.
            sec_items = _rating_first(sec_items)
            # Every item gets a full card. The "In brief" one-liner band was
            # removed at the reader's request — with only three sections there
            # is room, and a bullet with no summary read as a second-class
            # story rather than a space saver.
            parts.extend(_np_card(it) for it in sec_items)
    return "\n".join(parts), total, chosen


def _np_partc(top5: list[dict], date_str: str) -> str:
    """Top-5 table in the exact Part C markup the 7:30 email body uses.

    (The three-band Action/Watch/Context layout was tried and removed at the
    reader's request — this is the original single ranked list. Ordering
    still comes from the shared materiality score, so the most material item
    is number 01.)
    """
    rows = ""
    for i, it in enumerate(top5):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(top5) - 1 else ""
        label = SECTION_TITLES.get(it.get("section", "S2"), "News").upper()
        rows += (
            f'<tr valign="top">'
            f'<td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;'
            f'color:#cc0000;line-height:1;font-family:Georgia,serif;width:44px;">0{i + 1}</td>'
            f'<td style="padding:10px 16px 10px 4px;{border}">'
            f'<p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;'
            f'text-transform:uppercase;color:#888;">{label} &bull; {_esc(it["source"])}</p>'
            f'<p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">{_esc(it["title"])}</p>'
            f'</td></tr>'
        )
    if not rows:
        rows = ('<tr><td style="padding:10px 16px;color:#1a1a1a;font-size:12px;">'
                'No fresh items in your sections today.</td></tr>')
    return (
        f'<table id="takeaways" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">'
        f'<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;'
        f'text-transform:uppercase;color:#fff;">&#9679; TOP 5 HEADLINES &mdash; {date_str}</td></tr>'
        f'</table>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #e5e5e5;border-top:none;">{rows}</table>'
    )


def _np_build_attachment(part_b_html: str, today) -> str:
    """Three-page newspaper.

    send_credit_report.build_attachment() is hardcoded to five pages with an
    S4/S5 nav, and that file is not to be modified — so the team mail builds
    its own. Same visual language, three sections.
    """
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

    nav = "".join(
        f'<a href="#pg{n}">{t}</a>' for _sid, t, n in _NP_PAGES)

    pages = ""
    for sid, title, pnum in _NP_PAGES:
        content = buckets.get(sid) or empty
        if pnum == "1":
            pages += f"""
<div class="news-page front-page" id="pg1">
  <div class="mast-top">
    <div class="mast-left">{dow_full}<br>{edition}</div>
    <div class="mast-right">Credit &amp; Markets Intelligence</div>
  </div>
  <div class="mast-center">
    <div class="mast-name">CareEdge Daily News</div>
    <hr class="mast-rule">
  </div>
  <div class="mast-sub">
    <span>S1 Watchlist &middot; S2 Sector &middot; S3 Macro</span>
    <span class="red">&#128274; CONFIDENTIAL</span>
  </div>
  <nav class="navbar">{nav}</nav>
  <div class="columns">{content}</div>
  <div class="page-foot">
    <span>CareEdge Daily News &mdash; {date_str}</span>
    <span>Page 1 of 3</span><span>&#128274; Confidential</span>
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
  <div class="columns">{content}</div>
  <div class="page-foot">
    <span>CareEdge Daily News &mdash; {date_str}</span>
    <span>Page {pnum} of 3</span><span>&#128274; Confidential</span>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>CareEdge Daily News — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=PT+Serif:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 1.2cm 1.4cm; }}
  @page :first {{ margin-top: 0.5cm; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#f0ece4;font-family:'PT Serif',Georgia,serif;color:#111;font-size:11px}}
  .newspaper{{max-width:960px;margin:20px auto}}
  .news-page{{background:#fdfaf5;box-shadow:0 2px 24px rgba(0,0,0,.18);margin-bottom:28px;padding-bottom:20px;break-before:page;page-break-before:always}}
  .front-page{{break-before:auto;page-break-before:auto}}
  .mast-top{{display:flex;justify-content:space-between;align-items:flex-end;padding:14px 28px 6px;border-bottom:1px solid #aaa}}
  .mast-left{{font-size:8.5px;letter-spacing:1.5px;text-transform:uppercase;color:#555;line-height:1.8}}
  .mast-right{{font-size:8.5px;text-align:right;color:#555;line-height:1.8}}
  .mast-center{{text-align:center;padding:4px 28px 0}}
  .mast-name{{font-family:'Playfair Display',Georgia,serif;font-size:52px;font-weight:900;line-height:1;letter-spacing:-2px;color:#111}}
  .mast-rule{{border:none;border-top:3px double #111;margin:6px 0 0}}
  .mast-sub{{display:flex;justify-content:space-between;align-items:center;padding:5px 28px;border-bottom:3px solid #111;font-size:8.5px;letter-spacing:1px;text-transform:uppercase;color:#555}}
  .mast-sub .red{{color:#cc0000;font-weight:700;border:1px solid #cc0000;padding:1px 6px}}
  .navbar{{display:flex;border-bottom:2px solid #cc0000;background:#111}}
  .navbar a{{flex:1;text-align:center;padding:7px 4px;font-size:8px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;text-decoration:none;border-right:1px solid #333}}
  .navbar a:first-child{{color:#fff}}
  .navbar a:last-child{{border-right:none}}
  .page-header{{display:flex;justify-content:space-between;align-items:center;padding:8px 28px;border-bottom:3px solid #111;border-top:4px solid #cc0000}}
  .page-header .ph-meta{{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:#777}}
  .page-header .ph-title{{font-family:'Playfair Display',Georgia,serif;font-size:14px;font-weight:700;color:#111}}
  .page-header .ph-num{{font-size:26px;font-weight:900;font-family:'Playfair Display',Georgia,serif;color:#cc0000;line-height:1}}
  .columns{{padding:0 28px 8px;column-count:3;column-gap:22px;column-rule:1px solid #ccc;min-height:80px}}
  [data-section="banner"]{{column-span:all;margin:20px -28px 0;padding:5px 28px;border-top:3px solid;border-bottom:1px solid}}
  .sb{{font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;padding-top:6px;padding-bottom:6px}}
  .sb1{{color:#cc0000;border-color:#cc0000}}
  .sb2{{color:#b45309;border-color:#b45309}}
  .sb3{{color:#1e3a8a;border-color:#1e3a8a}}
  .art{{break-inside:avoid;padding:12px 0;border-bottom:1px solid #ddd}}
  .art .src{{margin:0 0 3px;font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;color:#999}}
  .art .hl{{margin:0 0 6px;font-size:14px;font-weight:700;font-family:Georgia,serif;line-height:1.25;color:#111}}
  .art .wh{{margin:0 0 5px;font-size:10.5px;color:#333;line-height:1.55}}
  .art .rm{{font-size:9px;color:#888;text-decoration:none;font-weight:600}}
  .art .also{{font-size:10px;color:#999}}
  .art.hero{{padding:12px 0 14px;border-bottom:2px solid #cc0000;margin-bottom:4px}}
  .art.hero .src{{color:#cc0000}}
  .art.hero .hl{{font-size:18px;font-weight:800;line-height:1.2}}
  .art.hero .wh{{font-size:11px;color:#222;line-height:1.7}}
  .art.hero .rm{{color:#cc0000;font-weight:700}}
  .ibh{{margin:14px 0 4px;font-size:8px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#999}}
  .ib{{margin:0 0 4px;font-size:9.5px;color:#555;line-height:1.5}}
  .ib a{{color:#999;font-size:8.5px;text-decoration:none}}
  .empty{{padding:10px 0;font-size:10px;color:#aaa;font-style:italic}}
  .page-foot{{display:flex;justify-content:space-between;border-top:1px solid #bbb;margin:8px 28px 0;padding-top:6px;font-size:8px;color:#888;letter-spacing:1px;text-transform:uppercase}}
  @media print {{ body{{background:#fff}} .news-page{{box-shadow:none;margin-bottom:0}} }}
</style></head>
<body><div class="newspaper">{pages}</div></body></html>"""


def _np_rebrand(html: str) -> str:
    """The 7:30 templates carry the 'Credit Intelligence News' masthead and
    repo-edit links; this mail is branded CareEdge Daily News and managed
    from the team console."""
    html = html.replace("Credit Intelligence News", "CareEdge Daily News")
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


def _send(to_addr: str, subject: str, html: str,
          attachment_html: str = "", attachment_name: str = "") -> None:
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    if attachment_html:
        msg = MIMEMultipart("mixed")
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(html, "html"))
        msg.attach(body)
        part = MIMEBase("text", "html")
        part.set_payload(attachment_html.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        msg.attach(part)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html"))
    msg["Subject"] = subject
    msg["From"] = f"CareEdge Daily News <{user}>"
    msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to_addr], msg.as_string())
    print(f"[mail] sent '{subject}' -> {to_addr}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _mark_sent_today() -> None:
    path = os.path.join(_REPO_ROOT, "data", "team_last_sent.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = datetime.datetime.now(IST).date().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": today}, f)
    _git_push(path)


def main() -> None:
    team = _load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%A, %d %B %Y")

    # Scheduled runs respect the holiday calendar; manual dispatch always sends.
    if os.environ.get("TEAM_SCHEDULED") == "true":
        if team.get("skip_sundays", True) and now.strftime("%A") == "Sunday":
            print("[skip] Sunday — no mail (skip_sundays enabled; manual runs still work)")
            return
        if now.date().isoformat() in team.get("holidays", []):
            print(f"[skip] {now.date().isoformat()} is in the holiday list — no mail")
            return

    print("Fetching news (free sources, no AI)...")
    # apply_seen=False: do NOT inherit the daily Claude report's memory —
    # otherwise items that report published are hidden from team mails
    # forever even though the team mail never delivered them. The team
    # mailer relies solely on its own team_seen.json.
    # per_company_cap=5: wider net than the 7:30 report's default of 3, because
    # this mail has its own mechanical junk filter (_is_team_junk) to strip the
    # technical-chart noise that Google often ranks above the real story.
    news_text, _summary = fetch_all_news(os.environ.get("NEWSAPI_KEY", ""),
                                         apply_seen=False, per_company_cap=5)
    items = [_parse_item(ln) for ln in news_text.splitlines() if ln.strip()]

    seen = _load_seen()
    items = [it for it in items if _key(it) not in seen]
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
    stale = [it for it in items if _is_stale(it, today_d)]
    items = [it for it in items if not _is_stale(it, today_d)]
    for it in stale[:8]:
        print(f"[stale] dropped (>48h old): [{it.get('pub')}] {it['title'][:70]}")
    n_stale = pre_stale - len(items)
    print(f"{len(items)} items after recency filter (dropped {n_stale})")

    pre_dup = len(items)
    items = _dedup_cross_source(items)
    n_dup = pre_dup - len(items)
    print(f"{len(items)} items after cross-source dedup (merged {n_dup})")

    phrases = [_phrase(r["company"]) for r in rows]
    sectors = _load_sectors(team)
    macro_kw = [str(k).strip().lower() for k in team.get("macro_keywords", []) if str(k).strip()]
    print(f"[sectors] {', '.join(f'{n}({len(k)}kw)' for n, k in sectors.items()) or 'none'}"
          f" | macro={len(macro_kw)}kw")
    for it in items:
        it["section"] = _classify_team(it, phrases, sectors, macro_kw)
        if it["section"] == "S2":
            it["sectors"] = _item_sectors(it, sectors)
        it["companies"] = _match_companies(it, rows)

    pre_offtopic = len(items)
    offtopic = [it for it in items if it["section"] is None]
    items = [it for it in items if it["section"] is not None]
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
    test_email = os.environ.get("TEST_EMAIL", "").strip().lower()
    test_sections_env = os.environ.get("TEST_SECTIONS", "").strip()
    test_sections = {s.strip().upper() for s in test_sections_env.split(",") if s.strip()} or None
    if test_email:
        print(f"[test] restricting this run to {test_email}"
              f"{' / sections ' + ','.join(sorted(test_sections)) if test_sections else ''}")

    people: dict[str, dict] = {}
    for r in rows:
        # Legacy rows tick S4/S5; both now live in S3. Deliberately NOT
        # _TEAM_SECTION_MAP — that maps classifier output, where "S3" still
        # means the old regulation bucket. Re-mapping row ticks with it would
        # rewrite a new-scheme S3 (macro) subscription to S2 on every load.
        secs = {_ROW_SECTION_MIGRATE.get(x, x) for x in r.get("sections", [])}
        if test_sections is not None:
            secs = secs & test_sections
        for name_f, email_f, send_f in ROLES:
            # In test mode, match by email regardless of the row's Send tick
            # — a manual test should not depend on that row happening to be
            # enabled. Normal runs keep the send_f gate exactly as before.
            if not test_email and not r.get(send_f):
                continue
            # A cell may hold several addresses ("a@x, b@x; c@x") — each
            # address gets its own personalized mail.
            for email in (e.strip() for e in re.split(r"[,;]", r.get(email_f, "")) if e.strip()):
                if test_email and email.strip().lower() != test_email:
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

    if not people:
        print("[route] nobody is enabled in team.json — no mails to send")
        _save_seen(items)
        return

    # Lazy import: send_credit_report imports helpers from this module at its
    # top level, so importing it here (after this module is fully loaded) is
    # safe, while a module-level import would be circular.
    import send_credit_report as _scr

    today = now.date()
    sent_count, failed = 0, []
    for email, p in people.items():
        part_b, total, person_items = _np_partb(p, items, by_section)

        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[mail] skipping {email} — nothing new in their sections")
            continue

        top5 = sorted(person_items, key=_story_score, reverse=True)[:5]
        part_c = _np_partc(top5, now.strftime("%d %B %Y"))
        body = _np_rebrand(_scr.build_email(part_c, today, _summary))
        attachment = _np_rebrand(_np_build_attachment(part_b, today))
        # One bad mailbox must not stop the rest of the team's mails.
        try:
            _send(email, f"CareEdge Daily News — {now:%d %b %Y}", body,
                  attachment_html=attachment,
                  attachment_name=f"CareEdge_Daily_News_{today:%Y%m%d}.html")
            sent_count += 1
        except Exception as exc:
            print(f"[mail] FAILED for {email}: {exc}")
            failed.append(email)

    if failed:
        print(f"[mail] {len(failed)} failed: {', '.join(failed)}")
        admin = os.environ.get("GMAIL_USER", "")
        if admin:
            try:
                _send(admin, "CareEdge Daily News — delivery failures",
                      "<p>Delivery failed for:</p><ul>" +
                      "".join(f"<li>{e}</li>" for e in failed) +
                      f'</ul><p><a href="{_MANAGE_URL}">Check addresses in the console</a></p>')
            except Exception:
                pass

    # Master edition (all companies, all sections) for the public archive.
    master_p = {"sections": {"S1", "S2", "S3"},
                "companies": {r["company"] for r in rows},
                "sectors": set(sectors) | {_row_sector(r) for r in rows}}
    m_partb, _m_total, _m_items = _np_partb(master_p, items, by_section)
    _write_archive(_np_rebrand(_np_build_attachment(m_partb, today)), today)

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

    if test_email:
        # A one-off test must not mark today as sent (that would block
        # tomorrow's real scheduled run) or teach the shared seen-memory
        # about items other GHs haven't received yet.
        print("[test] skipping seen-memory save and sent-today marker")
    else:
        _save_seen(items)
        _mark_sent_today()
    print("Done.")


if __name__ == "__main__":
    main()
