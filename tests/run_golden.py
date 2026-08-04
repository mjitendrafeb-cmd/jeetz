#!/usr/bin/env python3
"""(H) Regression suite for the 7:40 classifier.

Every case in golden_set.json is a real item that was reported as wrongly
categorised, or a real item that must keep working. Before this existed the
only feedback loop was somebody spotting a mistake in their inbox, and each
regex fix risked silently breaking an earlier one — which is exactly what
happened when a bare `shares?` was added to the relevance gate and let every
stock-price story through.

Run:  python3 tests/run_golden.py
Exit: 0 = all pass, 1 = at least one regression.
"""
import json
import os
import re
import sys
import types
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def _load():
    """Import the two modules under test without their network deps."""
    sys.path.insert(0, SCRIPTS)
    for name in ("fetch_bse", "fetch_ratings", "fetch_telegram", "fetch_web"):
        sys.modules.setdefault(name, types.ModuleType(name))

    # fetch_news's stock-move filter runs before the team mailer sees an item,
    # so the suite has to apply it too or it would test only half the pipeline.
    src = open(os.path.join(SCRIPTS, "fetch_news.py"), encoding="utf-8").read()
    ns = {"re": re}
    exec(src[src.index("_STOCK_MOVE_RE = re.compile"):
             src.index("def _is_market_ticker(")], ns)
    stock_move = ns["_STOCK_MOVE_RE"]

    ns2 = {"re": re}
    exec(src[src.index("_INDIC_SCRIPT_RE = re.compile"):
             src.index("def _is_market_ticker(")], ns2)
    non_english = ns2["_is_non_english"]

    fn = types.ModuleType("fetch_news")
    fn.fetch_all_news = lambda *a, **k: ("", {})
    fn.load_watchlist = lambda: []
    sys.modules["fetch_news"] = fn
    spec = importlib.util.spec_from_file_location(
        "send_team_news", os.path.join(SCRIPTS, "send_team_news.py"))
    stn = importlib.util.module_from_spec(spec)
    sys.modules["send_team_news"] = stn
    spec.loader.exec_module(stn)
    return stn, stock_move, non_english


def verdict(stn, stock_move, non_english, case):
    """Run one item through the same order the live pipeline uses."""
    raw = f'[{case.get("tags","")}]{case.get("source","ET")}: {case["title"]}'
    if non_english(raw):
        return None
    if stock_move.search(case["title"]):
        return None
    it = {
        "title": case["title"], "summary": case.get("summary", ""),
        "tags": case.get("tags", ""), "source": case.get("source", "ET"),
        "url": "", "pub": "05 Aug", "wl_company": "", "companies": [],
    }
    if stn._is_out_of_scope(it) or stn._is_team_junk(it):
        return None
    return stn._classify(it, [])


def main() -> int:
    stn, stock_move, non_english = _load()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "golden_set.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    failures = []
    for c in cases:
        got = verdict(stn, stock_move, non_english, c)
        if got != c["expect"]:
            failures.append((c, got))

    width = max(len(str(c["expect"])) for c in cases)
    for c in cases:
        got = verdict(stn, stock_move, non_english, c)
        mark = "ok  " if got == c["expect"] else "FAIL"
        print(f"{mark} want={str(c['expect']):>{width}}  got={str(got):>{width}}  "
              f"{c['title'][:62]}")

    print(f"\n{len(cases) - len(failures)}/{len(cases)} passed")
    if failures:
        print("\nREGRESSIONS:")
        for c, got in failures:
            print(f"  - {c['title'][:70]}")
            print(f"      expected {c['expect']}, got {got}")
            print(f"      why this case exists: {c['why']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
