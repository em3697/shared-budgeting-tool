# Python budget app — setup

This replaces the Apps Script version entirely. Your Google Sheet (with the
Transactions/Categories tabs you already have) is still the shared data
store — these scripts just read and write it directly instead of going
through Apps Script.

You can delete the Apps Script project and the `doGet` Web App deployment
once this is working — they're no longer needed.

## 0. Set up a shared private repo (recommended)

This is the easiest way to keep both your copies of the code identical and
push fixes to both of you at once.

**You (create it once):**
```bash
cd budget-python
git init
git add .
git commit -m "Initial budget app"
```
Then on GitHub: **New repository** → set it to **Private** → don't
initialize with a README (you already have one) → follow the "push an
existing repo" instructions it shows you, something like:
```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```
Then on the repo's **Settings → Collaborators**, add Matt's GitHub username
so he can clone it.

**Matt (one time):**
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

`.gitignore` already excludes `service_account.json` and the generated
`dashboard.html`, so neither of you will ever accidentally commit the
credential or clutter the repo with regenerated output — the key file still
gets shared separately (AirDrop/Signal, step 1 below), not through git.

**Going forward:** whenever you tweak the categorization logic or fix a bug,
`git add . && git commit -m "..." && git push`, and Matt just runs
`git pull` to get the same fix — no more manually re-sending updated files.

## 1. One-time: create a Google Cloud service account

This is the one genuinely new piece of setup. A service account is a
non-human Google identity your Python scripts authenticate as — think of it
as a robot user that you grant access to your specific Sheet.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and
   create a project (or use an existing one)
2. Enable two APIs for that project: **Google Sheets API** and
   **Google Drive API** (search each in the top search bar → Enable)
3. Go to **IAM & Admin > Service Accounts** → **Create Service Account**
   — any name is fine, e.g. "budget-app"
4. Once created, click into it → **Keys** tab → **Add Key** → **Create new
   key** → JSON → this downloads a `.json` file
5. Rename that file to `service_account.json` and place it in this same
   folder (it's already in `.gitignore` if you put this in git — never
   commit it, it's a credential)
6. Open the JSON file, find the `client_email` field — it looks like
   `budget-app@your-project.iam.gserviceaccount.com`
7. Open your Google Sheet → **Share** → paste that email in → give it
   **Editor** access

Both you and Matt need a copy of the *same* `service_account.json` file
(share it directly, e.g. AirDrop/Signal — not email/Slack where it might
get logged) — you don't each need your own service account, just your own
copy of this one key file sitting in your own copy of this folder.

## 2. One-time per person: install Python dependencies

```bash
pip install -r requirements.txt
```

## 3. One-time: fill in config.py

Open `config.py` and set:
- `SPREADSHEET_ID` — the long string in your Sheet's URL between `/d/` and `/edit`
- `PEOPLE` — should already be `["Elise", "Matt"]`, matching your Categories tab

Since `config.py` has no secrets in it (just the Sheet ID and your names),
commit and push it — that way Matt gets the correct values automatically via
`git pull` instead of needing to edit the file himself.

## 4. Weekly workflow (either of you, independently)

```bash
python import_sofi.py --person Elise --file ~/Downloads/sofi_export.csv
```
(swap `Elise` for `Matt` and point `--file` at their own export)

This categorizes, dedupes against what's already in the Sheet, and appends
only new rows — same behavior as the old Apps Script version, just running
locally.

Then, whenever you want to see current numbers:

```bash
python build_dashboard.py
```

This reads the Sheet fresh, computes the month's budget-vs-actual, and opens
a `dashboard.html` in your browser with the numbers baked in — no server,
no port, no CORS. Re-run it any time; it overwrites the file with fresh data.

## Why this fixes the bugs from the Apps Script version

- **No more silent Date auto-conversion.** Sheets does this coercion at the
  API level for `USER_ENTERED` writes; these scripts write with
  `value_input_option="RAW"`, so `"2026-07"` stays exactly that — text —
  never becomes a Date object.
- **No "which spreadsheet is active" ambiguity.** Every script opens the
  Sheet explicitly by `SPREADSHEET_ID`, every time.
- **No stale deployment gotcha.** There's no separate "deploy a new version"
  step — you're always running whatever's in the file on disk.

## Folder contents

| File | Purpose |
|---|---|
| `config.py` | Your Sheet ID, names, tab names — edit this first |
| `sheets_client.py` | Auth + read/write helpers |
| `categorize.py` | Keyword matching, budget lookups, person-name normalization |
| `import_sofi.py` | Weekly CLI import script |
| `build_dashboard.py` | Computes numbers, generates `dashboard.html` |
| `dashboard_template.html` | The page template `build_dashboard.py` fills in |
| `service_account.json` | Your credential — **not included**, you generate this in step 1 |
