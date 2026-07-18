"""Probe #20: find the base URL for BSE's debt API map and call
rdbtr / CTRPrimaryMkt with it. Runs on GitHub Actions. Not used by reports.
"""

import re
import signal

import requests

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
}

session = requests.Session()
session.headers.update(H)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, **kw):
    signal.alarm(60)
    try:
        return session.get(url, timeout=(10, 25), **kw)
    finally:
        signal.alarm(0)


def main():
    shell = get("https://www.bseindia.com/markets/debt/debt_home.aspx").text
    script = re.search(r'src="([^"]+main[^"]*\.js[^"]*)"', shell).group(1)
    url = script if script.startswith("http") else "https://www.bseindia.com" + (
        script if script.startswith("/") else "/" + script)
    js = get(url).text

    # how is the map consumed? look just before the map for the service class
    i = js.find('GetRbCorpBonds1:"/rbcorpbonds1/w"')
    print(f"BEFORE-MAP:\n{js[max(0, i - 1200):i]}\n", flush=True)

    # base URL candidates in the bundle
    for kw in ("BseIndiaAPI", "api.bseindia.com", "apiBaseUrl", "baseUrl", "apiUrl"):
        idxs = [m.start() for m in re.finditer(re.escape(kw), js)][:4]
        for n, ix in enumerate(idxs):
            print(f"CTX[{kw}#{n}]: {js[max(0, ix - 200):ix + 250]!r}"[:500], flush=True)

    # try candidate bases
    for base in ("https://api.bseindia.com/BseIndiaAPI/api",
                 "https://api.bseindia.com/RealTimeBseIndiaAPI/api",
                 "https://api.bseindia.com/BseIndiaAPI/api1",
                 "https://apiv3.bseindia.com/BseIndiaAPI/api",
                 "https://api.bseindia.com/msource/1d/debt"):
        for path, params in (("/rdbtr/w", {"fmdt": "17/07/2026", "todt": "17/07/2026"}),
                             ("/Mkt_debt_search_CTRPrimaryMkt_DownloadCSV_ng/w",
                              {"fmdt": "17/07/2026", "todt": "17/07/2026"})):
            u = base + path
            try:
                r = get(u, params=params)
                head = r.text[:120].replace("\n", " ")
                tag = "JSON!" if r.text[:1].strip() in "[{" or "json" in r.headers.get(
                    "content-type", "") else ""
                print(f"{tag} {u} -> {r.status_code} {head!r}", flush=True)
            except Exception as exc:
                print(f"{u} -> ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
