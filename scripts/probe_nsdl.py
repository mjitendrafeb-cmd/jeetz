"""One-off probe of NSDL's Resources > Data section to map new-issuance data.

Runs on the GitHub Actions runner (this repo's sandbox cannot reach NSDL).
Prints page titles, links, forms, tables and file downloads so the real
fetcher can be written against the actual site structure. Not used by reports.
"""

import re
import signal
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


class HardTimeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise HardTimeout()


signal.signal(signal.SIGALRM, _alarm)


def show(url: str, label: str, dump_chars: int = 0):
    print(f"\n{'=' * 70}\nPROBE [{label}] {url}", flush=True)
    signal.alarm(45)  # hard wall-clock cap per URL — trickling servers can't hang us
    try:
        r = session.get(url, timeout=(10, 20), allow_redirects=True)
    except HardTimeout:
        print("  HARD TIMEOUT (45s wall clock)", flush=True)
        return None
    except Exception as exc:
        print(f"  ERROR: {exc}", flush=True)
        return None
    finally:
        signal.alarm(0)

    ctype = r.headers.get("content-type", "?")
    print(f"  status={r.status_code} final_url={r.url} type={ctype} len={len(r.content)}", flush=True)
    if r.status_code != 200:
        print(f"  body[:500]: {r.text[:500]!r}", flush=True)
        return None
    if "html" not in ctype and "text" not in ctype:
        print(f"  non-HTML first bytes: {r.content[:200]!r}", flush=True)
        return r
    soup = BeautifulSoup(r.text, "html.parser")
    if soup.title:
        print(f"  title: {soup.title.get_text(strip=True)}", flush=True)
    links = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())[:90]
        links.append((a["href"][:250], text))
    print(f"  {len(links)} links:", flush=True)
    for href, text in links[:150]:
        print(f"    {href}  |  {text}", flush=True)
    for form in soup.find_all("form"):
        inputs = [
            f"{i.get('name')}={i.get('value', '')!r}"
            for i in form.find_all(["input", "select"])
            if i.get("name")
        ]
        print(f"  FORM action={form.get('action')} method={form.get('method')} inputs={inputs}", flush=True)
    for s in soup.find_all("script", src=True)[:20]:
        print(f"  SCRIPT src={s['src']}", flush=True)
    for iframe in soup.find_all("iframe", src=True):
        print(f"  IFRAME src={iframe['src']}", flush=True)
    tables = soup.find_all("table")
    print(f"  {len(tables)} tables", flush=True)
    for t in tables[:5]:
        for row in t.find_all("tr")[:6]:
            cells = [" ".join(c.get_text(" ", strip=True).split())[:45] for c in row.find_all(["th", "td"])]
            print(f"    ROW: {cells}", flush=True)
    if dump_chars:
        body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        print(f"  TEXT[:{dump_chars}]: {body[:dump_chars]}", flush=True)
    return r


def main():
    r = show("https://nsdl.com/resources/data", "data-page", dump_chars=2500)
    if r is not None:
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            href, text = a["href"], a.get_text(" ", strip=True).lower()
            blob = (href + " " + text).lower()
            if any(k in blob for k in ("issu", "primary", "activ", "debt", "bond", "ncd",
                                       "commercial", "data", "isin", "corporate")):
                if href.startswith(("javascript", "#", "mailto")) or href in seen:
                    continue
                seen.add(href)
                full = href if href.startswith("http") else "https://nsdl.com" + (
                    href if href.startswith("/") else "/" + href)
                show(full, f"follow:{text[:35]}", dump_chars=1500)
                if len(seen) >= 15:
                    break
    else:
        # fallback: main site nav might reveal the data section under another path
        show("https://nsdl.com/", "home", dump_chars=1500)


if __name__ == "__main__":
    sys.exit(main())
