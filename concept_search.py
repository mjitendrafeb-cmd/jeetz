#!/usr/bin/env python3
"""
concept_search.py — CLI analyst-mentor: search your knowledge base and get structured insight.

Usage:
  python concept_search.py "co-lending" --api-key KEY
  python concept_search.py "NBFC liquidity" --notes-dir docs/notes
  python concept_search.py "LCR norms" --api-key KEY --notes-dir /path/to/notes
"""
import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")

CONCEPT_PROMPT = """\
You are an experienced credit analyst and mentor. A junior analyst has asked about the concept below.
You have been given relevant excerpts from a curated knowledge base of research notes.

Use the knowledge base excerpts as grounding where relevant, but also draw on your own expertise.
Respond as a mentor who is clear, direct, and practical — not academic.

Concept / Question:
\"\"\"%s\"\"\"

Knowledge Base Context:
%s

Return ONLY valid JSON (no markdown, no preamble) with this exact structure:
{
  "concept_overview": "<2-4 sentence plain-language explanation of what this concept is>",
  "why_it_matters": "<2-4 sentences: why this matters from a credit/rating perspective, who is affected, what changes when this happens>",
  "key_learnings": [
    "<practical lesson 1 — something actionable a credit analyst should know>",
    "<practical lesson 2>",
    "<practical lesson 3>"
  ],
  "analyst_lens": {
    "risks": "<key credit/financial risks associated with this concept>",
    "opportunities": "<potential upsides or positive signals to watch for>",
    "monitor": "<specific indicators, ratios, or triggers to track>"
  },
  "questions": [
    "<sharp analytical question an analyst should ask when encountering this concept>",
    "<question 2>",
    "<question 3>"
  ]
}

Rules:
- Be concise and direct — no filler phrases like "It is worth noting that..."
- Every learning must be actionable, not just descriptive
- Questions should be sharp and specific, not generic ("What are the risks?" is too vague)
- Return ONLY the JSON object, nothing else
"""


def load_notes(notes_dir):
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                note = json.load(f)
                notes.append(note)
        except Exception:
            pass
    return notes


def flatten_note_text(note):
    """Flatten all text fields of a note into a single searchable string."""
    parts = []

    def add(val):
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list):
            for item in val:
                add(item)
        elif isinstance(val, dict):
            for v in val.values():
                add(v)

    for key in (
        "executive_summary", "summary", "key_takeaways", "takeaways",
        "entities_impacted", "entities", "monitoring_points", "learning",
        "related_topics", "tags", "category", "risk_analysis",
        "key_implications", "sentiment", "relevance"
    ):
        add(note.get(key, ""))

    return " ".join(parts)


def score_note(note, query_tokens):
    """Return a relevance score for a note given query tokens."""
    text = flatten_note_text(note).lower()
    score = 0
    for token in query_tokens:
        count = text.count(token)
        if count > 0:
            score += count
            # Bonus if token appears in high-signal fields
            for field in ("tags", "category", "related_topics"):
                val = note.get(field, "")
                field_text = " ".join(val) if isinstance(val, list) else str(val)
                if token in field_text.lower():
                    score += 3
    return score


def extract_snippet(note, query_tokens, max_len=300):
    """Extract the most relevant snippet from a note."""
    # Try to find a sentence or bullet containing a query token
    text = flatten_note_text(note)
    sentences = re.split(r'(?<=[.!?])\s+|\n', text)

    best = None
    best_hits = 0
    for sent in sentences:
        sent_lower = sent.lower()
        hits = sum(1 for t in query_tokens if t in sent_lower)
        if hits > best_hits:
            best_hits = hits
            best = sent.strip()

    if not best:
        # Fall back to first bullet of executive_summary or summary
        es = note.get("executive_summary", [])
        if es:
            best = es[0] if isinstance(es, list) else str(es)
        else:
            best = note.get("summary", "")

    if best and len(best) > max_len:
        best = best[:max_len].rsplit(" ", 1)[0] + "..."

    return best or ""


def search_notes(notes, query, top_n=5):
    """Return top-N most relevant (note, snippet) pairs for the query."""
    query_tokens = [t.lower().strip() for t in re.split(r'\s+', query) if len(t) > 2]
    if not query_tokens:
        query_tokens = [query.lower().strip()]

    scored = []
    for note in notes:
        score = score_note(note, query_tokens)
        if score > 0:
            snippet = extract_snippet(note, query_tokens)
            scored.append((score, note, snippet))

    scored.sort(key=lambda x: -x[0])
    return [(n, s) for _, n, s in scored[:top_n]]


def format_context(matches):
    """Format matched notes as context for Claude."""
    if not matches:
        return "(No directly relevant notes found in knowledge base — respond from general expertise)"

    lines = []
    for i, (note, snippet) in enumerate(matches, 1):
        source = note.get("source_file", f"Note {i}")
        date = note.get("date", "")
        date_str = f" [{date}]" if date else ""
        category = note.get("category", "")
        cat_str = f" — {category}" if category else ""
        lines.append(f"[{i}] {source}{date_str}{cat_str}")
        if snippet:
            lines.append(f"    {snippet}")
        lines.append("")

    return "\n".join(lines)


def call_claude(concept, context, api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    prompt = CONCEPT_PROMPT % (concept, context)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    # Get text block, skipping thinking blocks
    raw = ""
    for block in reversed(msg.content):
        if hasattr(block, "text"):
            raw = block.text.strip()
            break
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # Extract JSON object between first { and last }
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


def print_response(concept, result, matches):
    sep = "=" * 51
    thin = "-" * 51

    print(f"\n{sep}")
    print(f"CONCEPT: {concept.upper()}")
    print(sep)

    print("\n\U0001f4d6 CONCEPT OVERVIEW")
    print(result.get("concept_overview", ""))

    print(f"\n{thin}")
    print("\n\U0001f4a1 WHY IT MATTERS")
    print(result.get("why_it_matters", ""))

    learnings = result.get("key_learnings", [])
    if learnings:
        print(f"\n{thin}")
        print("\n\U0001f4ca KEY LEARNINGS")
        for i, item in enumerate(learnings, 1):
            print(f"  {i}. {item}")

    lens = result.get("analyst_lens", {})
    if lens:
        print(f"\n{thin}")
        print("\n\U0001f50d ANALYST LENS")
        if lens.get("risks"):
            print(f"  Risks:         {lens['risks']}")
        if lens.get("opportunities"):
            print(f"  Opportunities: {lens['opportunities']}")
        if lens.get("monitor"):
            print(f"  What to monitor: {lens['monitor']}")

    if matches:
        print(f"\n{thin}")
        print("\n\U0001f4c4 FROM YOUR KNOWLEDGE BASE")
        for note, snippet in matches:
            source = note.get("source_file", "Unknown")
            date = note.get("date", "")
            date_str = f" [{date}]" if date else ""
            snippet_str = f" — {snippet}" if snippet else ""
            print(f"  [{source}]{date_str}{snippet_str}")

    questions = result.get("questions", [])
    if questions:
        print(f"\n{thin}")
        print("\n❓ QUESTIONS ANALYSTS SHOULD ASK")
        for i, q in enumerate(questions, 1):
            print(f"  {i}. {q}")

    print(f"\n{sep}\n")


def main():
    p = argparse.ArgumentParser(
        description="Search your knowledge base and get analyst-mentor insight on any concept."
    )
    p.add_argument("concept", help="The concept or question to explore (e.g. 'co-lending')")
    p.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    p.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR,
                   help=f"Directory containing _note.json files (default: {DEFAULT_NOTES_DIR})")
    p.add_argument("--top", type=int, default=5,
                   help="Max number of knowledge base snippets to include (default: 5)")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: Set ANTHROPIC_API_KEY environment variable or pass --api-key")
        sys.exit(1)

    notes_dir = os.path.expanduser(args.notes_dir)
    notes = load_notes(notes_dir)

    if notes:
        print(f"Loaded {len(notes)} note(s) from: {notes_dir}")
    else:
        print(f"No notes found in: {notes_dir} — will respond from general expertise")

    matches = search_notes(notes, args.concept, top_n=args.top) if notes else []

    if matches:
        print(f"Found {len(matches)} relevant note(s) for '{args.concept}'")
    else:
        print(f"No matching notes found for '{args.concept}' — asking Claude from general expertise")

    print("Calling Claude...")

    context = format_context(matches)
    try:
        result = call_claude(args.concept, context, api_key)
    except json.JSONDecodeError as e:
        print(f"Claude returned bad JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Claude call failed: {e}")
        sys.exit(1)

    print_response(args.concept, result, matches)


if __name__ == "__main__":
    main()
