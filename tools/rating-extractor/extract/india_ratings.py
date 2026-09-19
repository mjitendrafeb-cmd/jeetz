"""India Ratings (Ind-Ra) parser — JSON API.

VALIDATED against real captured API responses (see
`captures/India_Ratings/api_bank_facility_data.json`, Bajaj Finance).
Strategy: plain HTTP against an unauthenticated JSON API. No browser needed,
despite the site itself being an Angular SPA that serves an identical shell
on every route.

The API chain, read out of the site's JS bundle:

1. `home/GetSearch?searchKey=<name>` -> issuerList (issuerID) and
   pressreleaseList (pressReleaseID, title, prDate).
2. `pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=<id>` ->
   title, date and an overview blurb only. No instrument detail.
3. `pressReleases/GetBankFacilityDataRatingLetter?pressReleaseId=<id>` ->
   the instrument table: instrument, bankName, rating, ratedAmount,
   maturity/issuance dates, coupon.

ACTION ATTRIBUTION — the hard rule. The facility endpoint gives current
rated positions, not actions; the action verbs live in the press release
title, e.g. "India Ratings Assigns Bajaj Finance's Additional Bank Loan
Facilities 'IND AAA'/Stable; Affirms Existing Ratings". When a title names
more than one action, which instrument each applies to is NOT determinable
from these endpoints, so every row is flagged ambiguous rather than
attributed by guesswork. A single-action title is applied to all rows.
"""

import json
import re

from . import common

SOURCE = "India Ratings"

ACTION_VERBS = [
    ("Assigned", r"\bassign(?:s|ed)\b"),
    ("Affirmed", r"\baffirm(?:s|ed)\b"),
    ("Upgraded", r"\bupgrad(?:es|ed)\b"),
    ("Downgraded", r"\bdowngrad(?:es|ed)\b"),
    ("Withdrawn", r"\bwithdraw(?:s|n|als?)\b"),
    ("Rating Watch", r"\brating watch\b|\bplaces?\b.{0,20}\bwatch\b"),
    ("Outlook Revised", r"\brevises?\b.{0,20}\boutlook\b|\boutlook revised\b"),
    ("Migrated", r"\bmigrat(?:es|ed)\b"),
]

# "IND AAA", "IND A1+", "IND AA-/Stable". Short-term tokens (A1+..A4) must
# precede the plain "A" alternative, which would otherwise match first and
# truncate "IND A1+" to "IND A".
RATING_RE = re.compile(
    r"\bIND\s+(AAA|AA[+-]?|A[1-4]\+?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C|D)(?![A-Za-z0-9])"
)
OUTLOOK_RE = re.compile(r"\b(Stable|Positive|Negative|Developing)\b", re.IGNORECASE)


def _actions_in_title(title: str) -> list[str]:
    if not title:
        return []
    found = []
    for label, pattern in ACTION_VERBS:
        if re.search(pattern, title, re.IGNORECASE):
            found.append(label)
    return found


def _parse_amount(value):
    """Return (verbatim text, value in Rs. crore).

    UNITS: India Ratings publishes rated amounts in INR MILLION — its own
    column header reads "Rated Amount (INR million)", and the word "crore"
    appears nowhere in the site's bundle. CRISIL and ICRA publish in crore,
    so these are divided by 10 to keep one unit across all three sources.
    Storing them unconverted would overstate every India Ratings amount
    tenfold (Bajaj Finance's bank facilities read as 800,000 here, i.e.
    Rs.80,000 crore, not Rs.8,00,000 crore).
    """
    if value in (None, "", "-"):
        return None, None
    raw = str(value).strip()
    try:
        millions = float(raw.replace(",", ""))
    except ValueError:
        return f"INR {raw} million", None
    return f"INR {raw} million", millions / 10.0


def _parse_rating(value):
    if not value:
        return None, None
    rating_m = RATING_RE.search(value)
    outlook_m = OUTLOOK_RE.search(value)
    rating = f"IND {rating_m.group(1)}" if rating_m else common.clean(value)
    return rating, (outlook_m.group(1).capitalize() if outlook_m else None)


def _iso_date(value):
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    if m:
        return m.group(1)
    return common.extract_date(str(value))


def parse(entity_name: str, aliases: list[str], raw_content, content_type: str = "json") -> list[dict]:
    """Parse India Ratings API output.

    `raw_content` is JSON text: either the GetBankFacilityDataRatingLetter
    response directly, or a wrapper {"title": ..., "facilities": [...]}
    supplying the press release title so actions can be attributed.
    """
    try:
        payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except json.JSONDecodeError:
        print("[india_ratings] content is not valid JSON")
        return []

    title = None
    if isinstance(payload, dict) and "facilities" in payload:
        title = payload.get("title")
        payload = payload["facilities"]

    groups = payload if isinstance(payload, list) else [payload]

    actions = _actions_in_title(title)
    if len(actions) == 1:
        action_type, action_ambiguous, action_reason = actions[0], 0, None
    elif len(actions) > 1:
        action_type, action_ambiguous = None, 1
        action_reason = (
            f"The press release title states multiple actions ({', '.join(actions)}); "
            "which one applies to this instrument is not determinable from the "
            "facility endpoint, so it is not attributed."
        )
    else:
        action_type, action_ambiguous = None, 1
        action_reason = (
            "No press release title was supplied with the facility data, so no "
            "rating action can be attributed to this instrument — the endpoint "
            "reports current rated positions, not actions."
        )

    records = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        issuer = group.get("issuerName")
        if issuer and not common.mentions_entity(issuer, entity_name, aliases):
            print(f"[india_ratings] Facility group is for '{issuer}', not "
                  f"'{entity_name}' — skipping.")
            continue

        pub_date = _iso_date(group.get("pressreleasedate"))
        for facility in group.get("bankFacilitiesList") or []:
            amount_raw, amount_val = _parse_amount(facility.get("ratedAmount"))
            rating, outlook = _parse_rating(facility.get("rating"))
            bank = common.clean(facility.get("bankName") or "")
            instrument = common.clean(facility.get("instrument") or "")

            records.append({
                "instrument": f"{instrument} — {bank}" if bank else instrument,
                "record_date": _iso_date(facility.get("pressreleasedate")) or pub_date,
                "amount_raw_text": amount_raw,
                "amount_rs_cr": amount_val,
                "rating_current": rating,
                "rating_previous": None,
                "outlook_current": outlook,
                "outlook_previous": None,
                "action_type": action_type,
                "is_confirmed_action": 1 if action_type else 0,
                "ambiguous": action_ambiguous,
                "ambiguous_reason": action_reason,
                "provenance": "bank_facility_rating_letter",
                "row_seq": len(records),
                "is_sublimit": 0,
                "previous_amount_rs_cr": None,
                # Quote the source's own unit (INR million), not the converted
                # crore figure — this string is what a human reads when
                # checking a row against the press release.
                "evidence_text": common.clean(
                    f"{instrument} | {bank} | {facility.get('rating')} | "
                    f"rated amount {facility.get('ratedAmount')} (INR million, as published)"
                )[:500],
            })
    return records
