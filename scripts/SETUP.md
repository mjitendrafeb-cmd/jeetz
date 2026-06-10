# Setup Guide — Daily Credit Intelligence Report

## Prerequisites

### 1. Enable Gmail 2-Factor Authentication
Gmail App Passwords require 2FA to be active on your Google account.

1. Go to https://myaccount.google.com/security
2. Under "How you sign in to Google", enable **2-Step Verification**

### 2. Generate a Gmail App Password
1. Go to https://myaccount.google.com/apppasswords
2. Under "Select app" choose **Mail**; under "Select device" choose **Other (custom name)** and enter `GitHub Actions`
3. Click **Generate** — copy the 16-character password shown (spaces don't matter)

---

## Adding GitHub Secrets

In your GitHub repository:

1. Navigate to **Settings → Secrets and variables → Actions**
2. Click **New repository secret** for each of the following:

| Secret Name         | Value                                      |
|---------------------|--------------------------------------------|
| `GMAIL_USER`        | Your full Gmail address (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD`| The 16-character App Password generated above  |

---

## Triggering a Manual Test Run

1. Go to **Actions** tab in your GitHub repository
2. Select **Daily Credit Intelligence Report** from the left sidebar
3. Click **Run workflow** → **Run workflow** (branch: `main` or your default branch)
4. Check your inbox at `jitendra.meghrajani@gmail.com` within ~1 minute

---

## Schedule

The workflow runs automatically at **6:00 AM IST (00:30 UTC)** on Monday–Friday.

Cron expression: `30 0 * * 1-5`
