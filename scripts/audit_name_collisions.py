"""One-off audit: scan the full watchlist for the two name-collision bug
classes fixed for Shriram Credit (vs DCM Shriram) and Karnataka State
Financial Corporation (vs bare "Karnataka" state-government news) --
group-prefix rows whose tail word isn't actually distinctive, and a lone
identifying word that's short/generic enough to misfire -- plus a general
shared-prefix report so a human can sanity-check anything not already
covered by _COMMON/_GROUP_PREFIX_RE.

Read-only -- does not modify team.json or send_team_news.py. Run from the
repo root or scripts/ directory: python3 scripts/audit_name_collisions.py

Real bug hunting note: neither of the two confirmed bugs this script's
categories were built from was FOUND by a static audit like this one --
both were traced from an actual headline in a real sent edition. Treat
this script's output as a candidate list to watch for, not proof that any
of them have actually misfired.
"""
import json
import os
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import send_team_news as tn

team = json.load(open(os.path.join(_ROOT, "team.json"), encoding="utf-8"))
rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
names = [r["company"] for r in rows]

print(f"=== {len(rows)} watchlist rows ===\n")

# --- 1. Group-prefix rows: is the tail actually distinctive? ---
print("=== Group-prefix rows (_GROUP_PREFIX_RE) -- tail word check ===")
gp_hits = []
for name in names:
    m = tn._GROUP_PREFIX_RE.match(name.strip())
    if not m:
        continue
    prefix = m.group(0)
    rest = name[m.end():]
    tail = [w.strip(".,()").lower() for w in rest.split()]
    tail = [w for w in tail if len(w) >= 3 and w not in tn._FILLER and w not in tn._SUFFIXES]
    distinctive = [w for w in tail if w not in tn._COMMON]
    generic_only = tail and not distinctive
    gp_hits.append((name, prefix, tail, distinctive, generic_only))

for name, prefix, tail, distinctive, generic_only in gp_hits:
    flag = "  <-- ALL TAIL WORDS GENERIC (needs adjacency -- protected by today's fix)" if generic_only else ""
    print(f"  [{prefix:14s}] {name:55s} tail={tail} distinctive={distinctive}{flag}")
print(f"({len(gp_hits)} rows match a known group prefix)\n")

# --- 2. Lone-word risk: first sig word alone, len>=7, not in _COMMON ---
print("=== Lone-word risk: a single word (len>=7, not _COMMON) could identify the row alone ===")
lone_risk = []
for name in names:
    words = tn._sig_words(name)
    if not words:
        continue
    w0 = words[0]
    if len(words) == 1:
        risky = w0 not in tn._COMMON
    else:
        risky = len(w0) >= 7 and w0 not in tn._COMMON
    if risky:
        lone_risk.append((name, w0, words))

for name, w0, words in lone_risk:
    print(f"  {name:60s} lone-word='{w0}'  sig_words={words}")
print(f"({len(lone_risk)} rows rely on a single word >=7 chars for identification)\n")

# --- 3. Shared first-word across MULTIPLE watchlist rows (not necessarily
#        a known group prefix) -- worth a human glance even if the
#        mechanical checks above don't flag anything. ---
print("=== First significant word shared by 3+ different watchlist rows ===")
by_first = defaultdict(list)
for name in names:
    words = tn._sig_words(name)
    if words:
        by_first[words[0]].append(name)
for w0, group in sorted(by_first.items(), key=lambda kv: -len(kv[1])):
    if len(group) >= 3:
        print(f"  '{w0}' ({len(group)} rows): {group}")
