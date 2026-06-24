#!/usr/bin/env python3
"""
PR Audit Web App — CareEdge Ratings
Upload a latest PR (and optionally an older PR) and receive a structured AI audit report.
"""
import os
from flask import Flask, render_template, request, jsonify
import anthropic

from extractor import extract_text, read_excel_as_text
from system_prompt import SYSTEM_PROMPT

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB max upload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_FILES = os.path.join(BASE_DIR, "project_files")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

MODELS = {
    "claude-opus-4-8": "Claude Opus 4 (Best quality)",
    "claude-sonnet-4-6": "Claude Sonnet 4 (Faster)",
}


def _allowed(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _load_project_file(*filenames) -> tuple[bytes | None, str]:
    for fn in filenames:
        path = os.path.join(PROJECT_FILES, fn)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read(), fn
    return None, ""


def _build_user_message(latest_text, older_text, checklist_text, draft_non_so, draft_so) -> str:
    older_block = older_text.strip() if older_text.strip() else "No older PR provided."
    checklist_block = (
        checklist_text.strip()
        if checklist_text.strip()
        else "[CHECKLIST FILE NOT FOUND — place PR_checklist_AI_guidance_V1.xlsx in the project_files/ directory]"
    )
    non_so_block = (
        draft_non_so.strip()
        if draft_non_so.strip()
        else "[DRAFT PR (NON-SO) NOT FOUND — place PR_Draft_V1.pdf or .docx in project_files/]"
    )
    so_block = (
        draft_so.strip()
        if draft_so.strip()
        else "[DRAFT PR (SO) NOT FOUND — place Securitisation_PR_Format_Feb2025.pdf or .docx in project_files/]"
    )

    return f"""The following documents have been uploaded for PR audit. Full text has been pre-extracted programmatically using pypdf/python-docx. Treat this extracted text as the output of the mandatory pypdf extraction step described in your role instructions — this is the sole source of truth for all PR Completeness Check string searches and checkpoint evaluations. Do not attempt to re-extract.

{'━'*60}
LATEST PR — FULL EXTRACTED TEXT (pypdf output)
{'━'*60}
{latest_text}

{'━'*60}
OLDER PR — FULL EXTRACTED TEXT (for comparison)
{'━'*60}
{older_block}

{'━'*60}
PR CHECKLIST EXCEL — ALL SHEETS
{'━'*60}
{checklist_block}

{'━'*60}
DRAFT PR TEMPLATE — NON-SO RATING (PR Draft_V1)
{'━'*60}
{non_so_block}

{'━'*60}
DRAFT PR TEMPLATE — SO RATING (Securitisation PR Format Feb 2025)
{'━'*60}
{so_block}

{'━'*60}
Please conduct the complete PR audit following all role instructions and the mandatory execution protocol. Output the full audit report as HTML with all inline styles as specified in the output format instructions. Do not output any text before or after the HTML.
"""


@app.route("/")
def index():
    return render_template("index.html", models=MODELS)


@app.route("/health")
def health():
    files_status = {
        "checklist": os.path.exists(os.path.join(PROJECT_FILES, "PR_checklist_AI_guidance_V1.xlsx")),
        "draft_non_so": any(
            os.path.exists(os.path.join(PROJECT_FILES, fn))
            for fn in ["PR_Draft_V1.pdf", "PR_Draft_V1.docx"]
        ),
        "draft_so": any(
            os.path.exists(os.path.join(PROJECT_FILES, fn))
            for fn in ["Securitisation_PR_Format_Feb2025.pdf", "Securitisation_PR_Format_Feb2025.docx"]
        ),
    }
    return jsonify({"status": "ok", "project_files": files_status})


@app.route("/audit", methods=["POST"])
def audit():
    # --- API key ---
    api_key = (request.form.get("api_key", "") or "").strip()
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "Anthropic API key required. Enter it in the form or set ANTHROPIC_API_KEY."}), 400

    model = request.form.get("model", "claude-opus-4-8")
    if model not in MODELS:
        model = "claude-opus-4-8"

    # --- Latest PR (required) ---
    latest_file = request.files.get("latest_pr")
    if not latest_file or not latest_file.filename:
        return jsonify({"error": "Latest PR file is required."}), 400
    if not _allowed(latest_file.filename):
        return jsonify({"error": f"Unsupported file type. Please upload PDF or DOCX."}), 400

    latest_bytes = latest_file.read()
    latest_text = extract_text(latest_bytes, latest_file.filename)
    if not latest_text.strip():
        return jsonify({
            "error": "Could not extract text from the latest PR. The PDF may be scanned/image-based. "
                     "Please ensure the document is text-selectable."
        }), 400

    # --- Older PR (optional) ---
    older_text = ""
    older_file = request.files.get("older_pr")
    if older_file and older_file.filename and _allowed(older_file.filename):
        older_bytes = older_file.read()
        older_text = extract_text(older_bytes, older_file.filename)

    # --- Bundled project files ---
    checklist_text = ""
    checklist_path = os.path.join(PROJECT_FILES, "PR_checklist_AI_guidance_V1.xlsx")
    if os.path.exists(checklist_path):
        try:
            checklist_text = read_excel_as_text(checklist_path)
        except Exception as e:
            checklist_text = f"[Checklist read error: {e}]"

    draft_non_so_bytes, draft_non_so_fn = _load_project_file("PR_Draft_V1.pdf", "PR_Draft_V1.docx")
    draft_non_so = extract_text(draft_non_so_bytes, draft_non_so_fn) if draft_non_so_bytes else ""

    draft_so_bytes, draft_so_fn = _load_project_file(
        "Securitisation_PR_Format_Feb2025.pdf", "Securitisation_PR_Format_Feb2025.docx"
    )
    draft_so = extract_text(draft_so_bytes, draft_so_fn) if draft_so_bytes else ""

    # --- Call Claude ---
    user_message = _build_user_message(latest_text, older_text, checklist_text, draft_non_so, draft_so)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        report_html = message.content[0].text

        # Strip markdown fences if model wrapped the output
        for fence in ("```html", "```"):
            if report_html.startswith(fence):
                report_html = report_html[len(fence):]
        if report_html.endswith("```"):
            report_html = report_html[:-3]

        return jsonify({"html": report_html.strip()})

    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please verify your Anthropic API key."}), 401
    except anthropic.RateLimitError:
        return jsonify({"error": "API rate limit reached. Please wait a moment and try again."}), 429
    except anthropic.BadRequestError as e:
        return jsonify({"error": f"Request too large or malformed: {e}"}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
