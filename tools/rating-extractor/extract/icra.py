"""ICRA rationale parser (PDF).

VALIDATED against a real captured rationale
(`captures/ICRA/rationale_chola_pdf_2.pdf`, Cholamandalam, 19-Feb-2025).
Strategy: plain HTTP download + PDF table extraction. No browser needed —
ICRA serves rationales as text-based PDFs from
`/Rating/GetRationalReportFilePdf?id=<id>`.

The "Summary of rating action" table on page 1 is the authoritative source:
it gives, per instrument, the previous and current rated amount (Rs. crore)
and an explicit action ("reaffirmed", "assigned", "reaffirmed and
withdrawn"). That explicit per-instrument action is what satisfies the
action-vs-mention rule, so only these rows are recorded as confirmed
actions.

Layout note: an instrument's name is a single ruled cell that may span two
data rows (e.g. the NCD programme block covers both a reaffirmed and a
withdrawn line), and the wrapped name can sit visually *between* its own
data rows. Row grouping therefore follows the table's ruling lines rather
than text lines, which is the only reliable way to attach each amount to
the right instrument.
"""

import re

from . import common

SOURCE = "ICRA"

INSTRUMENT_COL_MAX_X = 225.0
PREV_COL = (225.0, 300.0)
CURR_COL = (300.0, 376.0)
ACTION_COL_MIN_X = 376.0

AMOUNT_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")

# "[ICRA]AA+ (Positive); reaffirmed", "PP-MLD[ICRA]AA+ (Positive); reaffirmed",
# "[ICRA]AA+ (Positive)/[ICRA]A1+; reaffirmed", "[ICRA]A1+; reaffirmed"
RATING_RE = re.compile(r"((?:PP-MLD)?\[ICRA\][A-D0-9+\-]+(?:\s*/\s*\[ICRA\][A-D0-9+\-]+)?)")
OUTLOOK_RE = re.compile(r"\((Positive|Negative|Stable|Developing)\)", re.IGNORECASE)
ACTION_RE = re.compile(
    r";\s*(reaffirmed and withdrawn|reaffirmed|assigned|upgraded|downgraded|"
    r"withdrawn|placed on watch[^,;]*|removed from watch[^,;]*|outlook revised[^,;]*)",
    re.IGNORECASE,
)


def _parse_amount(text: str):
    """Parse an amount cell -> (raw, value, is_sublimit).

    '22,995.30' -> 22995.30; '-' -> None. A parenthesised amount such as
    '(100.00)' is a SUB-LIMIT carved out of another rated facility, not
    additional rated debt — ICRA excludes it from the table's own total, so
    it is flagged and must not be summed with the rest.
    """
    if not text or text.strip() in {"-", "–", "—"}:
        return None, None, 0
    raw = text.strip()
    is_sublimit = 1 if raw.startswith("(") and raw.endswith(")") else 0
    cleaned = raw.strip("()").replace(",", "")
    try:
        return raw, float(cleaned), is_sublimit
    except ValueError:
        return raw, None, is_sublimit


def _subject_and_date(page_text: str):
    date = None
    m = re.search(
        r"(?i)\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s*\d{4}\b",
        page_text,
    )
    if m:
        date = common.extract_date(m.group(0))

    subject = None
    m2 = re.search(r"(?m)^\s*(.{4,120}?)\s*:\s", page_text)
    if m2:
        subject = common.clean(m2.group(1))
    return subject, date


def _rows_from_summary_table(page):
    """Group words into (instrument, [data lines]) blocks using ruling lines."""
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    tables = page.find_tables(table_settings=settings)
    if not tables:
        return []

    # The summary table is the one whose instrument column starts at the left
    # margin and which spans the widest area.
    table = max(tables, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
    words = page.extract_words()

    blocks = []
    rows = sorted(table.rows, key=lambda r: r.bbox[1])
    for i, row in enumerate(rows):
        top = row.bbox[1]
        bottom = rows[i + 1].bbox[1] if i + 1 < len(rows) else table.bbox[3]
        in_block = [w for w in words if top - 1 <= w["top"] < bottom - 1]
        if not in_block:
            continue

        instrument = common.clean(" ".join(
            w["text"] for w in sorted(
                (w for w in in_block if w["x0"] < INSTRUMENT_COL_MAX_X),
                key=lambda w: (round(w["top"]), w["x0"]))
        ))

        # Data lines within the block, grouped by visual line.
        by_line = {}
        for w in in_block:
            if w["x0"] < INSTRUMENT_COL_MAX_X:
                continue
            by_line.setdefault(round(w["top"] / 4) * 4, []).append(w)

        data_lines = []
        for key in sorted(by_line):
            line_words = sorted(by_line[key], key=lambda w: w["x0"])
            prev_txt = " ".join(w["text"] for w in line_words
                                if PREV_COL[0] <= w["x0"] < PREV_COL[1])
            curr_txt = " ".join(w["text"] for w in line_words
                                if CURR_COL[0] <= w["x0"] < CURR_COL[1])
            action_txt = " ".join(w["text"] for w in line_words
                                  if w["x0"] >= ACTION_COL_MIN_X)
            data_lines.append((key, prev_txt.strip(), curr_txt.strip(), action_txt.strip()))

        blocks.append((instrument, data_lines))
    return blocks


def _records_from_blocks(blocks, pub_date):
    records = []
    for instrument, data_lines in blocks:
        if not instrument or re.match(r"(?i)^(instrument|total)\b", instrument):
            continue
        if re.search(r"(?i)rs\.?\s*crore|rating action|previous rated|current rated", instrument):
            continue

        # A tranche's rating text does not reliably share a line with its
        # amounts — for a withdrawn tranche it sits on the line *above*, with
        # the trailing verb on the line below. Association rule: text starting
        # with a rating token begins a new tranche's action (held until that
        # tranche's amounts appear); text that does not is a continuation of
        # the most recent tranche.
        stitched = []
        pending_action = ""
        for key, prev_txt, curr_txt, action_txt in data_lines:
            has_amount = (bool(AMOUNT_RE.match(prev_txt or ""))
                          or bool(AMOUNT_RE.match(curr_txt or ""))
                          or (prev_txt or curr_txt) in {"-", "–", "—"})
            if has_amount:
                action = action_txt or pending_action
                pending_action = ""
                stitched.append([prev_txt, curr_txt, action.strip()])
            elif action_txt:
                if RATING_RE.match(action_txt.strip()):
                    pending_action = action_txt
                elif stitched:
                    stitched[-1][2] = f"{stitched[-1][2]} {action_txt}".strip()
                else:
                    pending_action = f"{pending_action} {action_txt}".strip()

        for prev_txt, curr_txt, action_txt in stitched:
            prev_raw, prev_val, _ = _parse_amount(prev_txt)
            curr_raw, curr_val, curr_sublimit = _parse_amount(curr_txt)

            rating_m = RATING_RE.search(action_txt)
            outlook_m = OUTLOOK_RE.search(action_txt)
            action_m = ACTION_RE.search(action_txt)

            rating = common.clean(rating_m.group(1)) if rating_m else None
            action = action_m.group(1).strip().title() if action_m else None

            ambiguous = 0
            reason = None
            if not rating or not action:
                ambiguous = 1
                reason = ("Could not read an explicit rating and action from the "
                          f"summary table cell: {action_txt!r}")

            records.append({
                "instrument": instrument,
                "record_date": pub_date,
                # Current amount stands alone: a withdrawn tranche shows "-"
                # here, and falling back to the previous amount would report
                # withdrawn debt as still rated.
                "amount_raw_text": curr_raw,
                "amount_rs_cr": curr_val,
                "rating_current": rating,
                "rating_previous": None,
                "outlook_current": outlook_m.group(1).capitalize() if outlook_m else None,
                "outlook_previous": None,
                "action_type": action,
                "is_confirmed_action": 1 if (rating and action) else 0,
                "ambiguous": ambiguous,
                "ambiguous_reason": reason,
                "provenance": "summary_of_rating_action",
                "row_seq": len(records),
                "is_sublimit": curr_sublimit,
                "previous_amount_rs_cr": prev_val,
                "evidence_text": common.clean(
                    f"{instrument} | prev {prev_txt or '-'} | curr {curr_txt or '-'} | {action_txt}"
                )[:500],
            })
    return records


def parse(entity_name: str, aliases: list[str], raw_content, content_type: str = "pdf") -> list[dict]:
    """Parse an ICRA rationale PDF.

    `raw_content` is a path to the PDF file (PDFs are binary, so unlike the
    HTML parsers this takes a path rather than decoded text).
    """
    try:
        import pdfplumber
    except ImportError:
        print("[icra] pdfplumber is required to parse ICRA rationale PDFs "
              "(pip install pdfplumber)")
        return []

    with pdfplumber.open(raw_content) as pdf:
        page = pdf.pages[0]
        page_text = page.extract_text() or ""
        subject, pub_date = _subject_and_date(page_text)

        if subject and not common.mentions_entity(subject, entity_name, aliases):
            print(f"[icra] Document subject is '{subject}', not '{entity_name}' — skipping.")
            return []

        blocks = _rows_from_summary_table(page)

    return _records_from_blocks(blocks, pub_date)
