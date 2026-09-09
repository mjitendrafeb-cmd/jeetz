"""India Ratings (Ind-Ra) parser.

PLACEHOLDER: not yet validated against a real India Ratings page (network to
indiaratings.co.in is blocked in the dev sandbox this was built in).
Currently strips HTML to text and runs the generic paragraph-level
classifier in `extract.common`. Once a real sample is available via
`ingest_sample.py --source "India Ratings"`, replace with a parser tuned to
Ind-Ra's actual rationale layout.
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
