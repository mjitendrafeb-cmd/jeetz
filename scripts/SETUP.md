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

| Secret Name          | Value                                                                 |
|----------------------|-----------------------------------------------------------------------|
| `GMAIL_USER`         | Your full Gmail address (e.g. `you@gmail.com`)                        |
| `GMAIL_APP_PASSWORD` | The 16-character App Password generated above                         |
| `ANTHROPIC_API_KEY`  | API key from [console.anthropic.com](https://console.anthropic.com) → **API Keys** |
| `NEWSAPI_KEY`        | API key from [newsapi.org](https://newsapi.org) — free tier, optional but recommended for broader coverage |

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

---

## GitHub Pages — Config Web App

A browser/mobile config interface is available at the repo's GitHub Pages URL.

### Enable GitHub Pages

1. Go to your repository on GitHub
2. Navigate to **Settings → Pages**
3. Under **Source**, select **Deploy from a branch**
4. Set **Branch** to `main` and folder to `/docs`
5. Click **Save**
6. After a minute, your app will be live at:
   `https://mjitendrafeb-cmd.github.io/jeetz/`

### Using the Config App

- On first visit, you'll be prompted for a GitHub Personal Access Token (PAT)
- Generate one at: **github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)**
- Select only the `repo` scope, then paste the token in the app
- The token is stored in your browser's `localStorage` only — never sent anywhere except the GitHub API
- From the app you can:
  - Edit and save `watchlist.txt` (Watchlist tab)
  - Toggle news sources on/off (News Sources tab)
  - Select which sections appear in the report (Sections tab)
  - Change the recipient email (Settings tab)
  - Trigger an immediate test report run (Settings tab → 🚀 button)
