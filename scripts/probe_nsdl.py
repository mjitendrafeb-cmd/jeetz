"""Probe #19: dump BSE's full debt API map and call the CP/CD endpoints.
Runs on the GitHub Actions runner. Not used by reports.
"""

import datetime
import json
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

    i = js.find('GetrdbRFQCPCD')
    print(f"MAP CONTEXT:\n{js[max(0, i - 2500):i + 2500]}", flush=True)

    today = datetime.date(2026, 7, 17)
    prev = today - datetime.timedelta(days=1)
    f1, t1 = prev.strftime("%d/%m/%Y"), today.strftime("%d/%m/%Y")
    f2, t2 = prev.strftime("%Y%m%d"), today.strftime("%Y%m%d")

    for name in ("rdbRFQCPCD", "rcds", "rdbtr", "rdbTradensettle", "wdsc"):
        for params in (None,
                       {"fmdt": f1, "todt": t1},
                       {"strPrevDate": f2, "strToDate": t2}):
            u = f"https://api.bseindia.com/BseIndiaAPI/api/{name}/w"
            try:
                r = get(u, params=params)
                ct = r.headers.get("content-type", "")
                if "json" in ct or r.text[:1].strip() in "[{":
                    print(f"\nHIT {name} {params} -> {r.status_code} JSON[:1500]: {r.text[:1500]}", flush=True)
                    break
                else:
                    print(f"{name} {params} -> {r.status_code} {ct} (html)", flush=True)
            except Exception as exc:
                print(f"{name} {params} -> ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
