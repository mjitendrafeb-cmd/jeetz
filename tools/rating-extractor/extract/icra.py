"""ICRA parser.

PLACEHOLDER: not yet validated against a real ICRA rating-rationale page
(network to icra.in is blocked in the dev sandbox this was built in).
Currently strips HTML to text and runs the generic paragraph-level
classifier in `extract.common`. ICRA's public rating-action listing is
table-based (per the sibling cra-rating-tracker project's earlier scraper) —
once a real sample is available via `ingest_sample.py --source ICRA`,
prefer parsing that table directly over free-text regex.
"""

from bs4 import BeautifulSoup

from . import common


def parse(entity_name: str, aliases: list[str], raw_content: str, content_type: str = "html") -> list[dict]:
    if content_type == "html":
        soup = BeautifulSoup(raw_content, "html.parser")
        text = soup.get_text(separator=" ")
    else:
        text = raw_content
    return common.generic_extract(entity_name, aliases, text)
