"""Shared parsing helpers: regex extraction + the action-vs-mention classifier.

IMPORTANT: this module has not been validated against real CRISIL/ICRA/India
Ratings markup (see README "Status: reconnaissance blocked"). The regexes
below are reasonable-effort based on how these agencies typically phrase
rating actions, but every one of them needs to be checked against a real
saved page via `ingest_sample.py` before being trusted.
"""

import re
from datetime import datetime

AGENCY_NAMES = {
    "CRISIL": ["CRISIL Ratings", "CRISIL"],
    "ICRA": ["ICRA Ratings", "ICRA"],
    "India Ratings": ["India Ratings", "India Ratings and Research", "Ind-Ra"],
}

ACTION_VERBS = {
    "Upgraded": r"upgrad\w*",
    "Downgraded": r"downgrad\w*",
    "Reaffirmed": r"reaffirm\w*",
    "Assigned": r"assign\w*",
    "Withdrawn": r"withdraw\w*",
    "Rating Watch": r"(placed|retained).{0,20}(on\s+)?(rating\s+)?watch",
    "Outlook Revised": r"revis\w*.{0,20}outlook|outlook.{0,20}revis\w*",
    "Suspended": r"suspend\w*",
}

# An "action statement" names the agency (or uses passive "has been") acting
# ON the rating/instrument, in the same breath as one of the verbs above.
# e.g. "CRISIL Ratings has upgraded the long-term rating on the bank
# facilities of <Entity> to..." or "the rating has been reaffirmed at...".
_AGENCY_ALT = "|".join(re.escape(n) for names in AGENCY_NAMES.values() for n in names)
ACTION_STATEMENT_RE = re.compile(
    rf"(?:(?:{_AGENCY_ALT})\s+has\s+\w+|"
    rf"the\s+(?:long[- ]term|short[- ]term|\w+)?\s*ratings?\s+(?:has|have)\s+been\s+\w+|"
    rf"has\s+been\s+\w+)",
    re.IGNORECASE,
)

_SCALE = r"(?:AAA|AA\+|AA-|AA|A\+|A-|A(?!\d)|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|B(?!\d)|C|D)"
_SHORT_SCALE = r"A[1-4]\+?|D"
RATING_RE = re.compile(
    rf"\b(?:[A-Z][a-zA-Z]{{2,20}}\s)?(?:{_SCALE}|{_SHORT_SCALE})\b(?:\s*\(([A-Za-z][A-Za-z ]+)\))?"
)

AMOUNT_RE = re.compile(
    r"(?:Rs\.?|₹|INR)\s?([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh)",
    re.IGNORECASE,
)

INSTRUMENT_KEYWORDS = [
    "long term bank facilities", "short term bank facilities", "bank loan facilities",
    "bank facilities", "term loan", "cash credit", "working capital",
    "non convertible debenture", "non-convertible debenture", "ncd",
    "commercial paper", "cp programme", "bond", "debenture", "fixed deposit",
    "overdraft", "letter of credit", "proposed", "long term instrument",
    "short term instrument",
]

DATE_PATTERNS = [
    r"\b\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[-/ ]\d{2,4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
]
DATE_RE = re.compile("|".join(DATE_PATTERNS))


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_into_units(text: str) -> list[str]:
    """Split press-release text into paragraph-ish units for classification."""
    text = clean(text)
    # Split on sentence boundaries, but keep units reasonably long so an
    # action verb and the entity name that share a sentence stay together.
    units = re.split(r"(?<=[.;])\s+(?=[A-Z])", text)
    return [u.strip() for u in units if u.strip()]


def mentions_entity(unit: str, entity_name: str, aliases: list[str]) -> bool:
    unit_l = unit.lower()
    names = [entity_name] + [a for a in aliases if a]
    return any(name.lower() in unit_l for name in names if name)


def classify_unit(unit: str, entity_name: str, aliases: list[str]) -> dict:
    """Classify one text unit for the entity: confirmed action, or just a mention.

    HARD RULE: a unit is only 'confirmed' when it names the entity AND
    contains an explicit action-statement pattern (agency + verb, or
    passive 'has been <verb>') in the SAME unit. Anything else that
    mentions the entity is 'ambiguous' (needs human review), never
    silently promoted to a rating change.
    """
    if not mentions_entity(unit, entity_name, aliases):
        return {"relevant": False}

    action_type = None
    for label, pattern in ACTION_VERBS.items():
        if re.search(pattern, unit, re.IGNORECASE):
            action_type = label
            break

    has_action_statement = bool(ACTION_STATEMENT_RE.search(unit))

    if action_type and has_action_statement:
        return {
            "relevant": True,
            "confirmed": True,
            "action_type": action_type,
            "reason": None,
        }

    if action_type or has_action_statement:
        return {
            "relevant": True,
            "confirmed": False,
            "action_type": action_type,
            "reason": "Mentions the entity and an action-like word, but no clear "
            "agency-acts-on-entity statement in the same unit — could be a "
            "restatement, a group-company reference, or genuinely an action; verify manually.",
        }

    return {
        "relevant": True,
        "confirmed": False,
        "action_type": None,
        "reason": "Entity is mentioned but no rating-action language found in this unit "
        "— likely contextual (e.g. group company, historical preamble), not an action.",
    }


def extract_rating(text: str):
    m = RATING_RE.search(text)
    if not m:
        return None, None
    return clean(m.group(0)), (clean(m.group(1)) if m.group(1) else None)


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


def extract_date(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return m.group(0)


def generic_extract(entity_name: str, aliases: list[str], full_text: str) -> list[dict]:
    """Fallback extractor: classify each text unit mentioning the entity.

    UNVALIDATED against real site markup — see module docstring. Produces
    one candidate record per relevant unit; `ingest_sample.py` is where you
    check these against the actual source page before trusting any of it.
    """
    records = []
    for unit in split_into_units(full_text):
        result = classify_unit(unit, entity_name, aliases)
        if not result.get("relevant"):
            continue

        rating, outlook = extract_rating(unit)
        amount_text, amount_crore = extract_amount(unit)
        records.append(
            {
                "instrument": extract_instrument(unit),
                "record_date": extract_date(unit),
                "amount_raw_text": amount_text,
                "amount_rs_cr": amount_crore,
                "rating_current": rating,
                "rating_previous": None,
                "outlook_current": outlook,
                "outlook_previous": None,
                "action_type": result.get("action_type"),
                "is_confirmed_action": 1 if result.get("confirmed") else 0,
                "ambiguous": 0 if result.get("confirmed") else 1,
                "ambiguous_reason": result.get("reason"),
                "evidence_text": unit[:500],
            }
        )
    return records
