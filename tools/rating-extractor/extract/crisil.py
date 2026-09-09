"""CRISIL parser.

PLACEHOLDER: not yet validated against a real CRISIL rating-rationale page
(network to crisilratings.com is blocked in the dev sandbox this was built
in). Currently strips HTML to text and runs the generic paragraph-level
classifier in `extract.common`. Once a real sample page is available via
`ingest_sample.py --source CRISIL`, replace this with a parser that reads
CRISIL's actual instrument table (rationale pages typically list
instrument / rated amount / rating in a structured block) instead of
free-text regex.
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
