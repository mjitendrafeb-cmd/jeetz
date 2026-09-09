"""CRISIL Ratings rationale parser.

VALIDATED against real captured rationale pages (see
`captures/CRISIL/rationale_bajaj_finance*.html`, fetched by the CI recon
workflow). Strategy: plain HTTP + HTML table parsing. No browser needed —
the rationale documents are fully server-rendered.

Three structures are parsed, each recorded with its own `provenance`:

1. Header "Rating Action" table — instrument rows whose rating cell carries
   an explicit action in parentheses, e.g. "Crisil AAA/Stable (Reaffirmed)".
   These are the only rows treated as a confirmed rating ACTION taken on
   this entity in this release (the hard rule).
2. `#AnnexureSecTableId` — per-facility breakdown (facility, rated amount,
   lender, rating). Amounts, not actions.
3. `#AnnexRtgHistoryTable` — CRISIL's own dated rating history per
   instrument, which yields previous vs new rating over time.
"""

import re

from bs4 import BeautifulSoup

from . import common

SOURCE = "CRISIL"

# CRISIL's HTML contains stray spaces inside words ("Rs . 25000 C rore"),
# so the amount pattern tolerates whitespace between every character group.
AMOUNT_RE = re.compile(
    r"Rs\s*\.?\s*([\d,]+(?:\.\d+)?)\s*C\s*r\s*o\s*r\s*e", re.IGNORECASE
)

ACTION_IN_PARENS_RE = re.compile(
    r"\((Reaffirmed|Assigned|Upgraded|Downgraded|Withdrawn|Suspended|"
    r"Placed on [^)]+|Removed from [^)]+|Continues on [^)]+|Revised[^)]*)\)",
    re.IGNORECASE,
)

# "Crisil AAA/Stable", "Crisil A1+", "Crisil AA-/Negative".
# Short-term tokens (A1+..A4) must come first: a leading "A" alternative
# would otherwise match and truncate "A1+" to "A".
RATING_TOKEN_RE = re.compile(
    r"(?:Crisil|CRISIL)\s+(A[1-4]\+?|(?:AAA|AA|BBB|BB|B|C|D|A)[+-]?)"
    r"(?:\s*/\s*(Stable|Positive|Negative|Developing|Watch[^\s,)]*))?",
    re.IGNORECASE,
)

LT_SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
            "BB+", "BB", "BB-", "B+", "B", "B-", "C", "D"]
ST_SCALE = ["A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4", "D"]


def _rank(rating: str):
    """Position on the rating scale; lower index = stronger. None if unknown.

    Ratings are stored prefixed ("Crisil AAA"), so the agency name is
    stripped before looking the token up on the scale.
    """
    if not rating:
        return None, None
    r = re.sub(r"(?i)^\s*crisil\s+", "", rating).upper().replace(" ", "")
    if r in LT_SCALE:
        return LT_SCALE.index(r), "LT"
    if r in ST_SCALE:
        return ST_SCALE.index(r), "ST"
    return None, None


def _direction(previous: str, new: str):
    """Upgraded / Downgraded / Reaffirmed from two ratings, or None if unrankable."""
    p_rank, p_scale = _rank(previous)
    n_rank, n_scale = _rank(new)
    if p_rank is None or n_rank is None or p_scale != n_scale:
        return None
    if n_rank < p_rank:
        return "Upgraded"
    if n_rank > p_rank:
        return "Downgraded"
    return "Reaffirmed"


def _parse_rating_cell(text: str):
    m = RATING_TOKEN_RE.search(text)
    if not m:
        return None, None
    rating = f"Crisil {m.group(1).upper()}"
    outlook = m.group(2).capitalize() if m.group(2) else None
    return rating, outlook


def _parse_amount(text: str):
    m = AMOUNT_RE.search(text)
    if not m:
        return None, None
    raw = re.sub(r"\s+", "", m.group(0))
    try:
        return raw, float(m.group(1).replace(",", ""))
    except ValueError:
        return raw, None


def _instrument_name(text: str) -> str:
    """Strip the amount clause out of a left-hand instrument cell."""
    cleaned = AMOUNT_RE.sub(" ", text)
    cleaned = re.sub(r"\(.*?\)", " ", cleaned)
    cleaned = re.sub(r"(?i)\baggregating\b", " ", cleaned)
    return common.clean(cleaned) or common.clean(text)


def _subject_entity(soup) -> str | None:
    """The entity this rationale is about — the lead-in of the header table."""
    for table in soup.find_all("table")[:4]:
        row = table.find("tr")
        if not row:
            continue
        text = common.clean(row.get_text(" ", strip=True))
        m = re.match(r"^(.{3,120}?)\s*['‘’\"]", text)
        if m:
            return common.clean(m.group(1))
    return None


def _press_release_date(html: str):
    m = re.search(
        r"(?i)\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s*\d{4}\b",
        html,
    )
    return common.extract_date(m.group(0)) if m else None


def _header_action_records(soup, pub_date):
    """Rows whose rating cell states an explicit action — the confirmed actions."""
    records = []
    pending_total_amount = None

    # CRISIL nests the summary tables inside a wrapper <table>, so parsing
    # every table would yield each row twice. Only innermost tables are read,
    # which keeps genuinely repeated rows (two same-size NCD programmes).
    for table in soup.find_all("table"):
        if table.find("table") is not None:
            continue
        for row in table.find_all("tr"):
            cells = [common.clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if len(cells) != 2:
                continue
            left, right = cells

            # "Total Bank Loan Facilities Rated | Rs.46000 Crore" supplies the
            # amount for the Long/Short Term Rating rows that follow it.
            if re.search(r"(?i)total bank loan facilities rated", left):
                _, pending_total_amount = _parse_amount(right)
                continue

            action_match = ACTION_IN_PARENS_RE.search(right)
            if not action_match:
                continue
            rating, outlook = _parse_rating_cell(right)
            if not rating:
                continue

            amount_text, amount_cr = _parse_amount(left)
            instrument = _instrument_name(left)
            if re.fullmatch(r"(?i)(long|short) term rating", instrument):
                instrument = f"Bank Loan Facilities ({instrument.split()[0].title()} Term)"
                if amount_cr is None:
                    amount_cr = pending_total_amount
                    amount_text = f"Rs.{pending_total_amount} Crore" if pending_total_amount else None

            records.append({
                "instrument": instrument,
                "record_date": pub_date,
                "amount_raw_text": amount_text,
                "amount_rs_cr": amount_cr,
                "rating_current": rating,
                "rating_previous": None,
                "outlook_current": outlook,
                "outlook_previous": None,
                "action_type": action_match.group(1).title(),
                "is_confirmed_action": 1,
                "ambiguous": 0,
                "ambiguous_reason": None,
                "provenance": "header_action_table",
                # A release can rate two programmes that are identical in every
                # visible field (e.g. two Rs.15,000cr NCD programmes). Position
                # in the table is the only thing distinguishing them, so it is
                # carried through rather than collapsing them into one row.
                "row_seq": len(records),
                "evidence_text": common.clean(f"{left} | {right}")[:500],
            })
    return records


def _bank_facility_records(soup, pub_date):
    """#AnnexureSecTableId: facility | amount | lender | rating (amounts, not actions)."""
    table = soup.find(id="AnnexureSecTableId")
    if not table:
        return []
    records = []
    for row in table.find_all("tr"):
        cells = [common.clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if len(cells) != 4:
            continue
        facility, amount, lender, rating_text = cells
        if re.search(r"(?i)^facility$|^amount", facility):
            continue
        rating, outlook = _parse_rating_cell(rating_text)
        try:
            amount_cr = float(amount.replace(",", ""))
        except ValueError:
            amount_cr = None
        records.append({
            "instrument": f"{facility} — {lender}",
            "record_date": pub_date,
            "amount_raw_text": f"Rs.{amount} Crore" if amount else None,
            "amount_rs_cr": amount_cr,
            "rating_current": rating,
            "rating_previous": None,
            "outlook_current": outlook,
            "outlook_previous": None,
            "action_type": None,
            "is_confirmed_action": 0,
            "ambiguous": 0,
            "ambiguous_reason": "Facility-level breakdown from the annexure: a rated "
                                "amount for this facility, not a rating action in itself.",
            "provenance": "bank_facility_annexure",
            "evidence_text": " | ".join(cells)[:500],
        })
    return records


def _history_records(soup):
    """#AnnexRtgHistoryTable: dated rating history per instrument.

    Layout is a grid of (Date, Rating) pairs across year columns, with the
    instrument named only on the first row of each block. Consecutive dated
    entries give previous vs new rating.
    """
    table = soup.find(id="AnnexRtgHistoryTable")
    if not table:
        return []

    entries = []           # (instrument, date_iso, rating, outlook, raw)
    current_instrument = None
    date_re = re.compile(r"^\d{2}-\d{2}-\d{2}$")

    for row in table.find_all("tr"):
        cells = [common.clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if not cells or all(not c for c in cells):
            continue
        if cells[0] and not date_re.match(cells[0]) and cells[0] not in {"--", "Instrument"}:
            if not re.search(r"(?i)^(current|\d{4})", cells[0]):
                current_instrument = cells[0]

        for i, cell in enumerate(cells):
            if not date_re.match(cell):
                continue
            rating_text = cells[i + 1] if i + 1 < len(cells) else ""
            rating, outlook = _parse_rating_cell(rating_text)
            if not rating:
                continue
            day, month, year = cell.split("-")
            iso = f"20{year}-{month}-{day}"
            entries.append((current_instrument, iso, rating, outlook, f"{cell} {rating_text}"))

    records = []
    by_instrument = {}
    for instrument, iso, rating, outlook, raw in entries:
        by_instrument.setdefault(instrument, []).append((iso, rating, outlook, raw))

    for instrument, items in by_instrument.items():
        items.sort(key=lambda x: x[0])
        previous_rating = None
        for iso, rating, outlook, raw in items:
            # The oldest row is just where the displayed window starts — no
            # prior rating is shown, so the action behind it is unknown.
            # Calling it "Assigned" would be a guess.
            direction = _direction(previous_rating, rating) if previous_rating else None
            first_in_window = previous_rating is None
            records.append({
                "instrument": instrument,
                "record_date": iso,
                "amount_raw_text": None,
                "amount_rs_cr": None,
                "rating_current": rating,
                "rating_previous": previous_rating,
                "outlook_current": outlook,
                "outlook_previous": None,
                "action_type": direction,
                "is_confirmed_action": 1 if direction else 0,
                "ambiguous": 0 if direction else 1,
                "ambiguous_reason": None if direction else (
                    "Oldest entry in the displayed history window; no prior rating is "
                    "shown, so the action that produced it is unknown."
                    if first_in_window else
                    "Could not rank previous vs new rating to determine direction."),
                "provenance": "rating_history_annexure",
                "evidence_text": raw[:500],
            })
            previous_rating = rating
    return records


def parse(entity_name: str, aliases: list[str], raw_content: str,
          content_type: str = "html") -> list[dict]:
    if content_type != "html":
        return []

    soup = BeautifulSoup(raw_content, "html.parser")

    subject = _subject_entity(soup)
    if subject and not common.mentions_entity(subject, entity_name, aliases):
        print(f"[crisil] Document subject is '{subject}', not '{entity_name}' — skipping "
              f"(a rationale for another entity is not an action on this one).")
        return []

    pub_date = _press_release_date(raw_content)

    records = []
    records += _header_action_records(soup, pub_date)
    records += _bank_facility_records(soup, pub_date)
    records += _history_records(soup)
    return records
