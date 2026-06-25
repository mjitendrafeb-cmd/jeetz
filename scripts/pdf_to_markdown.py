#!/usr/bin/env python3
"""
Convert PDF to token-efficient Markdown for use in Claude projects.

Usage:
    python3 pdf_to_markdown.py input.pdf [output.md]
    python3 pdf_to_markdown.py input.pdf --stdout
"""

import sys
import re
import argparse
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Install PyMuPDF: pip install pymupdf", file=sys.stderr)
    sys.exit(1)


def extract_blocks(page):
    """Extract text blocks with font size info for heading detection."""
    blocks = []
    rawblocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    for b in rawblocks:
        if b["type"] != 0:  # skip images
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                blocks.append({
                    "text": text,
                    "size": span["size"],
                    "flags": span["flags"],  # bold=16, italic=2
                    "bbox": span["bbox"],
                    "block_bbox": b["bbox"],
                })
    return blocks


def detect_font_levels(all_blocks):
    """Map font sizes to heading levels (h1/h2/h3) vs body text."""
    sizes = sorted({round(b["size"]) for b in all_blocks}, reverse=True)
    # Body text is typically the most common size
    from collections import Counter
    size_counts = Counter(round(b["size"]) for b in all_blocks)
    body_size = size_counts.most_common(1)[0][0]

    levels = {}
    heading_sizes = [s for s in sizes if s > body_size + 1]
    for i, s in enumerate(heading_sizes[:3]):
        levels[s] = i + 1  # h1, h2, h3
    return levels, body_size


def is_bold(flags):
    return bool(flags & 16)


def is_list_item(text):
    # covers •, ·, –, —, -, *, +, and numbered lists
    return bool(re.match(r'^[•·–—\-\*\+]\s+', text) or
                re.match(r'^\d+[\.\)]\s+', text))


def clean_text(text):
    """Normalize whitespace and common PDF artifacts."""
    text = re.sub(r'\s+', ' ', text)
    # Remove soft hyphens and zero-width spaces
    text = text.replace('­', '').replace('​', '')
    return text.strip()


def blocks_to_markdown(pages_blocks, font_levels, body_size):
    lines = []
    prev_text = None
    prev_size = None

    for page_num, blocks in enumerate(pages_blocks):
        # Group consecutive spans into logical lines by y-position
        line_groups = {}
        for b in blocks:
            y = round(b["bbox"][1])
            if y not in line_groups:
                line_groups[y] = []
            line_groups[y].append(b)

        for y in sorted(line_groups):
            group = line_groups[y]
            # Merge spans on the same line
            texts = []
            sizes = []
            flags_list = []
            for span in group:
                t = clean_text(span["text"])
                if t:
                    texts.append(t)
                    sizes.append(round(span["size"]))
                    flags_list.append(span["flags"])

            if not texts:
                continue

            combined = " ".join(texts)
            dominant_size = max(set(sizes), key=sizes.count)
            dominant_flags = flags_list[sizes.index(dominant_size)]

            # Determine heading level
            level = font_levels.get(dominant_size)

            if level == 1:
                lines.append(f"\n# {combined}")
            elif level == 2:
                lines.append(f"\n## {combined}")
            elif level == 3:
                lines.append(f"\n### {combined}")
            elif is_list_item(combined):
                # Normalize bullet/number lists
                combined = re.sub(r'^[•·–—]\s+', '- ', combined)
                lines.append(combined)
            elif is_bold(dominant_flags) and dominant_size >= body_size:
                # Bold body text → treat as subheading if short, else bold inline
                if len(combined) < 80:
                    lines.append(f"\n**{combined}**")
                else:
                    lines.append(combined)
            else:
                lines.append(combined)

            prev_text = combined
            prev_size = dominant_size

    return lines


def merge_paragraphs(lines):
    """Join consecutive body lines into paragraphs; preserve headings/lists."""
    result = []
    para_buffer = []

    def flush():
        if para_buffer:
            result.append(" ".join(para_buffer))
            para_buffer.clear()

    for line in lines:
        if line.startswith(("\n#", "\n**")) or re.match(r'^[-\*\+] ', line):
            flush()
            result.append(line.strip())
        elif re.match(r'^\d+[\.\)]\s', line):
            flush()
            result.append(line)
        elif line.strip() == "":
            flush()
        else:
            para_buffer.append(line.strip())

    flush()
    return result


def deduplicate(lines):
    """Remove repeated headers/footers (page numbers, running titles)."""
    from collections import Counter
    counts = Counter(lines)
    # Remove lines that appear on nearly every page (likely headers/footers)
    # Keep if appears <= 2 times, or is a heading
    seen = set()
    result = []
    for line in lines:
        if counts[line] > 3 and not line.startswith("#"):
            continue  # probable header/footer repeated on each page
        result.append(line)
    return result


def post_process(text):
    """Final cleanup: collapse excess blank lines."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return text.strip()


def pdf_to_markdown(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages_blocks = []
    all_blocks = []

    for page in doc:
        blocks = extract_blocks(page)
        pages_blocks.append(blocks)
        all_blocks.extend(blocks)

    if not all_blocks:
        return ""

    font_levels, body_size = detect_font_levels(all_blocks)

    raw_lines = blocks_to_markdown(pages_blocks, font_levels, body_size)
    merged = merge_paragraphs(raw_lines)
    deduped = deduplicate(merged)

    markdown = "\n\n".join(deduped)
    markdown = post_process(markdown)

    doc.close()
    return markdown


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to token-efficient Markdown for Claude projects"
    )
    parser.add_argument("input", help="Path to input PDF file")
    parser.add_argument("output", nargs="?", help="Path to output .md file (default: same name as PDF)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of file")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Converting {pdf_path}...", file=sys.stderr)
    markdown = pdf_to_markdown(str(pdf_path))

    if args.stdout:
        print(markdown)
    else:
        out_path = Path(args.output) if args.output else pdf_path.with_suffix(".md")
        out_path.write_text(markdown, encoding="utf-8")

        # Token estimate (rough: 1 token ≈ 4 chars)
        pdf_size = pdf_path.stat().st_size
        md_chars = len(markdown)
        est_tokens = md_chars // 4
        print(f"Done: {out_path}", file=sys.stderr)
        print(f"PDF size:    {pdf_size:,} bytes", file=sys.stderr)
        print(f"MD chars:    {md_chars:,}", file=sys.stderr)
        print(f"Est. tokens: ~{est_tokens:,}", file=sys.stderr)


if __name__ == "__main__":
    main()
