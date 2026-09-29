"""Shared helpers for agency scrapers.

Every agency scraper takes a list of watchlist companies (each a dict with
"name" and "aliases") and returns a list of rating-action dicts (without
company_id/fetched_at, which the caller fills in). Fields the regex
extraction can't determine are left as None rather than guessed.

NOTE: These agencies redesign their public pages from time to time, and the
listing pages usually only carry a headline + link, not a structured table of
instrument/amount/rating. The extraction here is best-effort, run against the
snippet of text around each matching link. When a listing gives no more than
a headline, `instrument`/`amount_text`/`rating` will be None and the record
is still stored (with the source link) so nothing is silently dropped.
"""

import re
from datetime import datetime

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

RATING_KEYWORDS = [
    "rating", "upgrade", "downgrade", "reaffirm", "affirm", "withdraw",
    "watch", "outlook", "assign", "suspend",
]

ACTION_PATTERNS = [
    ("Upgraded", r"\bupgrad\w*"),
    ("Downgraded", r"\bdowngrad\w*"),
    ("Reaffirmed", r"\breaffirm\w*"),
    ("Withdrawn", r"\bwithdraw\w*"),
    ("Rating Watch", r"\b(rating\s+watch|watch\s+with)\w*"),
    ("Outlook Revised", r"\boutlook\s+revis\w*"),
    ("Assigned", r"\bassign\w*"),
    ("Suspended", r"\bsuspend\w*"),
]

# Long-term (AAA..D) and short-term (A1+..D) rating scale tokens, optionally
# prefixed by an agency name (e.g. "CRISIL AAA", "[ICRA]A1+").
_SCALE = r"(?:AAA|AA\+|AA-|AA|A\+|A-|A(?!\d)|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|B(?!\d)|C|D)"
_SHORT_SCALE = r"A[1-4]\+?|D"
RATING_RE = re.compile(
    rf"\b(?:[A-Z]{{2,12}}\s?)?(?:\[?[A-Z]+\]?\s?)?({_SCALE}|{_SHORT_SCALE})"
    r"(?:\s*\(([A-Za-z ]+)\))?"
)

AMOUNT_RE = re.compile(
    r"(?:Rs\.?|₹|INR)\s?([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh)",
    re.IGNORECASE,
)

INSTRUMENT_KEYWORDS = [
    "bank loan facilities", "bank facilities", "bank loan", "term loan",
    "cash credit", "non convertible debenture", "non-convertible debenture",
    "ncd", "commercial paper", "cp programme", "cp", "bond", "debenture",
    "fixed deposit", "working capital", "overdraft", "letter of credit",
]

DATE_PATTERNS = [
    r"\b\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[-/ ]\d{2,4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
]
DATE_RE = re.compile("|".join(DATE_PATTERNS))

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_html(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def matches_company(text: str, company: dict) -> bool:
    text_l = text.lower()
    names = [company["name"]] + [a for a in company.get("aliases", []) if a]
    return any(name.lower() in text_l for name in names if name)


def is_rating_related(text: str) -> bool:
    text_l = text.lower()
    return any(kw in text_l for kw in RATING_KEYWORDS)


def extract_action_type(text: str):
    text_l = text.lower()
    for label, pattern in ACTION_PATTERNS:
        if re.search(pattern, text_l):
            return label
    return None


def extract_rating(text: str):
    m = RATING_RE.search(text)
    if not m:
        return None, None
    rating = m.group(1)
    outlook = m.group(2)
    return rating, outlook


def extract_amount(text: str):
    m = AMOUNT_RE.search(text)
    if not m:
        return None, None
    raw_num, unit = m.group(1), m.group(2).lower()
    try:
        value = float(raw_num.replace(",", ""))
    except ValueError:
        return m.group(0), None
    if unit.startswith("lakh"):
        value = value / 100.0
    return m.group(0), value


def extract_instrument(text: str):
    text_l = text.lower()
    for kw in INSTRUMENT_KEYWORDS:
        if kw in text_l:
            return kw.title()
    return None


def extract_date(text: str):
    m = DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(0)
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw.replace(",", ""), fmt.replace(",", "")).date().isoformat()
        except ValueError:
            continue
    return raw


def build_action(agency, company, text, url):
    rating, outlook = extract_rating(text)
    amount_text, amount_crore = extract_amount(text)
    return {
        "agency": agency,
        "instrument": extract_instrument(text),
        "amount_text": amount_text,
        "amount_crore": amount_crore,
        "rating": rating,
        "outlook": outlook,
        "action_type": extract_action_type(text),
        "action_date": extract_date(text),
        "source_url": url,
        "raw_text": text[:500],
    }
