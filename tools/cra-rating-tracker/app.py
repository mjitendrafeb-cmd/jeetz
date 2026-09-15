#!/usr/bin/env python3
"""Local web dashboard for the CRA rating tracker."""

from flask import Flask, flash, redirect, render_template, request, url_for

import db
import fetch

app = Flask(__name__)
app.secret_key = "cra-rating-tracker-local"  # local single-user tool, not internet-facing


@app.route("/")
def index():
    with db.get_conn() as conn:
        companies = db.list_companies(conn)
        summary = []
        for company in companies:
            latest = db.latest_per_agency(conn, company["id"])
            summary.append({"company": company, "latest": latest})
    return render_template("index.html", summary=summary)


@app.route("/companies", methods=["POST"])
def add_company():
    name = request.form.get("name", "").strip()
    aliases = request.form.get("aliases", "").strip()
    if not name:
        flash("Company name is required.", "error")
        return redirect(url_for("index"))
    with db.get_conn() as conn:
        db.add_company(conn, name, aliases)
    flash(f"Added {name} to the watchlist.", "success")
    return redirect(url_for("index"))


@app.route("/companies/<int:company_id>/delete", methods=["POST"])
def delete_company(company_id):
    with db.get_conn() as conn:
        db.delete_company(conn, company_id)
    flash("Company removed.", "success")
    return redirect(url_for("index"))


@app.route("/companies/<int:company_id>")
def company_detail(company_id):
    with db.get_conn() as conn:
        company = db.get_company(conn, company_id)
        if company is None:
            flash("Company not found.", "error")
            return redirect(url_for("index"))
        history = db.history_for_company(conn, company_id)
    return render_template("company.html", company=company, history=history)


@app.route("/refresh", methods=["POST"])
def refresh_all():
    counts = fetch.run()
    total = sum(counts.values())
    flash(f"Refresh complete: {total} matching item(s) found.", "success")
    return redirect(url_for("index"))


@app.route("/companies/<int:company_id>/refresh", methods=["POST"])
def refresh_company(company_id):
    with db.get_conn() as conn:
        company = db.get_company(conn, company_id)
    if company is None:
        flash("Company not found.", "error")
        return redirect(url_for("index"))
    counts = fetch.run(only_name=company["name"])
    total = sum(counts.values())
    flash(f"Refresh complete for {company['name']}: {total} matching item(s) found.", "success")
    return redirect(url_for("company_detail", company_id=company_id))


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=5000)
