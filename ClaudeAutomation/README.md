# Claude PR Audit Automation

Automated batch processing of company PR documents through a Claude Project
that contains the `/pr-audit-master` custom Skill.

For every company folder in the `Queue/` directory the automation:

1. Opens Chrome using your existing logged-in profile (no re-login needed)
2. Navigates to your Claude Project
3. Opens a **new chat** (one per company — never mixed)
4. Uploads **every PDF** found in the company folder
5. Types and selects `/pr-audit-master`
6. Sends the message and waits for Claude to finish generating
7. Downloads the resulting HTML artifact
8. Saves it as `PR Audit Report.html` inside the same company folder
9. Creates `completed.ok` to mark success
10. Moves to the next folder

Folders that already contain `completed.ok` are skipped automatically,
making the automation safe to re-run after interruptions.

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10+ (3.13 recommended) |
| Google Chrome | Any recent version |
| Playwright | ≥ 1.44 |

---

## Installation

### 1 — Clone or copy the project

```
ClaudeAutomation/
├── automation.py
├── browser.py
├── config.py
├── config.json          ← edit this
├── download.py
├── helpers.py
├── logger.py
├── requirements.txt
├── run.bat
├── README.md
├── logs/
└── Queue/
    ├── 001_ABC Ltd/
    │   ├── PR1.pdf
    │   └── PR2.pdf
    └── 002_XYZ Ltd/
        ├── PR1.pdf
        └── PR2.pdf
```

### 2 — Install dependencies

```cmd
pip install -r requirements.txt
```

### 3 — Install Playwright's Chrome support

```cmd
python -m playwright install chrome
```

> **Note:** The automation uses *your installed Chrome*, not a Playwright-
> downloaded browser, so it inherits your existing Claude login session.
> The `playwright install chrome` command only installs support libraries.

---

## Chrome Profile Setup

The automation needs your **Chrome User Data directory** — the folder that
holds your cookies, so it can open Claude already logged in.

### Finding the path

1. Open Chrome and go to `chrome://version`
2. Look at **Profile Path** — for example:
   ```
   C:\Users\Alice\AppData\Local\Google\Chrome\User Data\Default
   ```
3. The **chrome_profile_path** in `config.json` is the parent folder:
   ```
   C:\Users\Alice\AppData\Local\Google\Chrome\User Data
   ```
4. The **chrome_profile_name** is the last component (`Default`, `Profile 1`, etc.)

### Important

Chrome **must be fully closed** before running the automation.
Two Chrome processes cannot safely share the same profile directory.
The automation will fail with a lock error if Chrome is open.

---

## Configuration

Edit **`config.json`** before the first run:

```json
{
    "project_url": "https://claude.ai/project/YOUR_PROJECT_ID_HERE",
    "queue_folder": "Queue",
    "chrome_profile_path": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Google\\Chrome\\User Data",
    "chrome_profile_name": "Default",
    "skill_name": "/pr-audit-master",
    "retry_count": 3,
    "download_timeout": 120000,
    "upload_timeout": 60000,
    "response_timeout": 300000,
    "navigation_timeout": 30000,
    "headless": false,
    "slow_mo": 100,
    "log_file": "logs/automation.log"
}
```

| Key | Description | Default |
|---|---|---|
| `project_url` | Full URL of your Claude Project | **(required)** |
| `queue_folder` | Relative or absolute path to the Queue folder | `Queue` |
| `chrome_profile_path` | Chrome User Data directory (parent of `Default/`) | **(required)** |
| `chrome_profile_name` | Profile sub-folder name inside User Data | `Default` |
| `skill_name` | Slash command to invoke | `/pr-audit-master` |
| `retry_count` | Upload / download / click retries per step | `3` |
| `download_timeout` | Max ms to wait for the Download button / file | `120000` |
| `upload_timeout` | Max ms to wait for uploads to finish | `60000` |
| `response_timeout` | Max ms to wait for Claude to finish generating | `300000` |
| `navigation_timeout` | Max ms for page navigation and element waits | `30000` |
| `headless` | Run Chrome without a visible window | `false` |
| `slow_mo` | Delay between Playwright actions (ms) — increase if Claude's UI lags | `100` |
| `log_file` | Path to the log file | `logs/automation.log` |

### Getting the project URL

1. Open Claude in Chrome and navigate to your Project
2. Copy the URL from the address bar — it looks like:
   ```
   https://claude.ai/project/proj_01AbCdEfGhIj
   ```

---

## Preparing the Queue

1. Create the `Queue/` folder (already exists if you used the project template)
2. Inside `Queue/`, create one sub-folder per company — name them however you like:
   ```
   Queue/
   ├── 001_ABC Ltd/
   │   ├── PR Document.pdf
   │   └── Annual Report.pdf
   └── 002_XYZ Corp/
       └── PR Q4.pdf
   ```
3. The automation uploads **every `*.pdf` file** in each folder — you do not
   need to name them specifically.

---

## Running the Automation

**Windows — easiest:**
```cmd
run.bat
```

**Any platform — directly:**
```cmd
python automation.py
```

**Custom config path:**
```cmd
python automation.py C:\path\to\my_config.json
```

---

## What Happens After Processing

Each company folder ends up looking like this:

```
Queue/001_ABC Ltd/
├── PR1.pdf
├── PR2.pdf
├── PR Audit Report.html   ← downloaded HTML artifact
└── completed.ok           ← success marker
```

If a folder fails, instead of `completed.ok` you get:

```
Queue/001_ABC Ltd/
├── PR1.pdf
├── PR2.pdf
├── failed.txt             ← full Python traceback
└── debug_failure_*.png   ← screenshot at time of failure
```

Re-running the automation skips completed folders and retries failed ones.

---

## Logs

All events are written to `logs/automation.log` and to the console:

```
2026-06-25 09:12 [INFO    ] Claude PR Audit Automation — Starting
2026-06-25 09:12 [INFO    ] Queue: 3 folder(s) total | 0 already done | 3 to process
2026-06-25 09:12 [INFO    ] ──────────────────────────────────────────────────────────────
2026-06-25 09:12 [INFO    ] Starting  : 001_ABC Ltd
2026-06-25 09:12 [INFO    ] Found 2 PDF(s): ['PR1.pdf', 'PR2.pdf']
2026-06-25 09:12 [INFO    ] Navigating to project URL…
2026-06-25 09:13 [INFO    ] Opening new chat…
2026-06-25 09:13 [INFO    ] New chat ready.
2026-06-25 09:13 [INFO    ] Uploading 2 PDF(s)…
2026-06-25 09:13 [INFO    ] All PDFs uploaded.
2026-06-25 09:13 [INFO    ] Invoking skill: /pr-audit-master
2026-06-25 09:13 [INFO    ] Skill selected.
2026-06-25 09:13 [INFO    ] Sending message…
2026-06-25 09:13 [INFO    ] Message sent — waiting for Claude to respond…
2026-06-25 09:13 [INFO    ] Claude is generating (stop button visible)…
2026-06-25 09:16 [INFO    ] Stop button hidden — Claude finished generating.
2026-06-25 09:16 [INFO    ] Waiting for HTML artifact Download button…
2026-06-25 09:16 [INFO    ] HTML artifact saved: PR Audit Report.html (48,321 bytes)
2026-06-25 09:16 [INFO    ] Completed: 001_ABC Ltd
```

---

## Troubleshooting

### "chrome_profile_path does not exist"
Double-check the path in `config.json`. On Windows the path uses double
backslashes: `"C:\\Users\\Alice\\AppData\\Local\\Google\\Chrome\\User Data"`.

### "Chrome is already open / profile is locked"
Close all Chrome windows completely before running the automation.
Check Task Manager for lingering `chrome.exe` processes.

### "Element not found" / selectors fail
Claude occasionally updates its UI. When this happens:

1. Open Chrome's DevTools (F12) on a Claude chat page
2. Use the inspector to find the current selector for the failing element
3. Add the new selector at the **top** of the relevant list in `browser.py`
   (look for the `SELECTORS` dictionary)

All selector lists accept multiple fallback entries — you do not need to
remove the old ones.

### "Send button never became enabled"
The PDFs may still be uploading when the skill is invoked. Increase
`upload_timeout` in `config.json` (default 60000 = 60 s).

### "Claude did not finish generating"
The skill may take longer than `response_timeout` (default 300000 = 5 min).
Increase it if your PDFs are large.

### "Download button not found"
The HTML artifact Download button selector may have changed. Inspect the
artifact panel in DevTools and update `SELECTORS["download_button"]` in
`browser.py`.

### Automation runs but Chrome shows "This site can't be reached"
Verify `project_url` in `config.json` points to your actual project.
Check that Chrome is logged into Claude in the profile specified.

---

## Security Notes

- Your Chrome profile (and therefore your Claude session) is used directly.
  Keep `config.json` out of version control if it contains your profile path.
- The automation does not transmit credentials — it simply drives Chrome as you.
- Use `"headless": false` (the default) so you can monitor progress and
  intervene if Claude shows an unexpected dialog.
