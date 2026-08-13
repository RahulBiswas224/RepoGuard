# Self Audit Scanner (Tool Which Exploit 💥🔥❤️‍🔥)
# I AM NOT RESPONSIBLE FOR ANY UNAUTHORIZED USAGE OF THIS PROJECT ! DAMMMM🫡

Scan **your own** public GitHub repos (across any number of accounts you
personally own) for accidentally leaked secrets — including secrets buried
in old or "deleted" commits that are still sitting in git history.

This is meant for auditing yourself, not other people's accounts. It only
scans repos owned by the usernames you pass in.

---

## What it does

`self_audit.py`:
1. Pulls the list of your public repos via the GitHub API, for each
   username you give it.
2. Shows an interactive menu so you choose exactly which repos to scan —
   all of them, one, or several specific ones.
3. Clones each selected repo with **full commit history** (not just the
   latest snapshot).
4. Runs [gitleaks](https://github.com/gitleaks/gitleaks) against the entire
   history, catching secrets even if you deleted them in a later commit —
   the old commit still holds the original content.
5. Prints any findings straight to your terminal — including the actual
   secret value, the file, the commit, and a direct link to it on GitHub —
   so you immediately know what to rotate.
6. Deletes every clone and every intermediate file it created, guaranteed,
   even if the run is interrupted or errors out.
7. Writes a summary of **only the repos with findings** to a JSON report.

`doc_scan.py` (optional): finds PDFs/docx in a cloned repo and uses Gemini
to check them for sensitive content that gitleaks can't catch — PII,
credentials pasted into prose, confidential markers, etc.

---

## Setup

```bash
# 1. Install gitleaks
brew install gitleaks       # macOS
scoop install gitleaks      # Windows (Scoop)
choco install gitleaks      # Windows (Chocolatey)
# or download the release binary matching your OS + CPU architecture:
# https://github.com/gitleaks/gitleaks/releases

# 2. Install python deps (only needed for doc_scan.py)
pip install google-generativeai pypdf python-docx

# 3. (recommended) create a GitHub personal access token
# https://github.com/settings/tokens — classic token, scope: public_repo only
# raises your rate limit from 60/hr to 5000/hr
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# 4. (optional, for doc_scan.py) get a Gemini API key
# https://aistudio.google.com/apikey
export GEMINI_API_KEY=xxxxxxxxxxxx
```

Verify everything is on `PATH` before running:
```bash
git --version
gitleaks version
python --version   # or python3, depending on your OS
```

---

## Usage

### Basic scan (interactive)

```bash
python self_audit.py --users your-username
```

This lists your public repos and shows a menu:

```
Found 8 public repos for your-username:

  1. Scan ALL repos
  2. QuickForm
  3. weather-app
  4. portfolio-site
  5. discord-bot-experiment
  6. react-todo
  7. old-scraper-project
  8. dotfiles
  9. leetcode-solutions
 10. Abort (skip your-username, scan nothing for this user)

Enter your choice for your-username (e.g. "1" for all, "2,3" for specific repos, "10" to abort):
```

- `1` → scan everything
- `3,5,7` → scan just those repos (comma-separated, any combination)
- `10` (or whatever the last number is) → abort, scan nothing for this user

If you pass multiple `--users`, you get a separate menu per user.

### All input options

| Flag | Required | Default | Description |
|---|---|---|---|
| `--users` | **Yes** | — | One or more GitHub usernames to audit, space-separated |
| `--token` | No | `$GITHUB_TOKEN` env var | GitHub personal access token — raises API rate limit from 60/hr to 5000/hr |
| `--workdir` | No | system temp dir | Where repos are cloned to during scanning |
| `--keep-clones` | No | off | Keep cloned repos on disk after scanning (cleanup is automatic otherwise) |
| `--output` | No | `audit_report.json` | Path to write the JSON summary report |
| `--redact-output` | No | off | Redact secret values in the saved report file (they still print to your console during the scan either way) |
| `--no-interactive` | No | off | Skip the repo-selection menu and scan **all** repos for every user — useful for automation/cron where nobody's there to answer the prompt |

### Examples

```bash
# Scan multiple accounts you own
python self_audit.py --users your-username your-other-username

# Custom output filename
python self_audit.py --users your-username --output report.json

# Keep clones around after scanning, for manual digging
python self_audit.py --users your-username --keep-clones --workdir ./clones

# Report file has secrets redacted (safe to share with a teammate)
python self_audit.py --users your-username --redact-output

# No prompts — scan everything automatically (for cron/CI)
python self_audit.py --users your-username --no-interactive
```

### What a run looks like

```
=== Auditing GitHub user: your-username ===

Found 8 public repos for your-username:
  1. Scan ALL repos
  ...
 10. Abort

Enter your choice for your-username: 2

  -> Scanning your-username/QuickForm ...
     SECRETS_FOUND (2 finding(s))

     --------------------------------------------
     RULE:    generic-api-key
     FILE:    .env
     COMMIT:  e4a1c9f2b8d3a7e6f1c0b9a8d7e6f5c4b3a2d1e0
     DATE:    2024-03-12T10:15:42Z
     AUTHOR:  your-username
     SECRET:  AIzaSyD-9tSrke7Z6cZg0f5o3xxxxxxxxxxx
     LINK:    https://github.com/your-username/QuickForm/commit/e4a1c9f2b8d3a7e6f1c0b9a8d7e6f5c4b3a2d1e0
     --------------------------------------------

==================================================
DONE. Total findings: 2 across 1 repo(s).
Full report written to: audit_report.json (contains raw secret values — keep this file private)

Repos needing attention (rotate these keys):
  - your-username/QuickForm: 2 finding(s)

Cleanup complete — no clones or temp files left on disk
```

### `audit_report.json`

**Only repos with findings are included** — clean repos are scanned but
skipped in the report, so the file only shows what needs action.

```json
[
  {
    "user": "your-username",
    "repo": "QuickForm",
    "status": "SECRETS_FOUND",
    "finding_count": 2,
    "findings": [
      {
        "rule": "generic-api-key",
        "file": ".env",
        "commit": "e4a1c9f2b8d3a7e6f1c0b9a8d7e6f5c4b3a2d1e0",
        "date": "2024-03-12T10:15:42Z",
        "author": "your-username",
        "commit_url": "https://github.com/your-username/QuickForm/commit/e4a1c9f2b8d3a7e6f1c0b9a8d7e6f5c4b3a2d1e0",
        "secret": "AIzaSyD-9tSrke7Z6cZg0f5o3xxxxxxxxxxx"
      }
    ]
  }
]
```

By default this file **contains the real secret values**, since the whole
point is knowing exactly what to rotate. Pass `--redact-output` if you want
a copy safe to archive or hand to a teammate instead — findings still print
in full to your console during the run regardless of this flag.

---

## If something is found

1. **Rotate/revoke the leaked credential immediately** at its source (Stripe
   dashboard, AWS IAM, database provider, etc.) — treat it as compromised
   the moment it existed in a public repo, no matter how long ago.
2. **Update everywhere the credential is actually used** — your local
   `.env`, CI/CD secrets, deployment configs.
3. **Optionally, remove it from git history** with
   [git-filter-repo](https://github.com/newren/git-filter-repo) or BFG
   Repo-Cleaner, then force-push. This is cleanup, not urgent — once
   rotated, the old value in history is dead, but scrubbing it keeps future
   scans quiet. Note this rewrites history: anyone who cloned before needs
   to re-clone.
4. **Delete `audit_report.json`** once you're done with it — it holds raw
   secret values by default, so there's no reason to keep it lying around
   after rotation.

---

## Scan documents in a specific repo (optional)

```bash
python self_audit.py --users your-username --keep-clones --workdir ./clones
python doc_scan.py ./clones/your-username/some-repo
```

---

## Cleanup and disk safety

- Every cloned repo is deleted immediately after it's scanned, not just at
  the end of the whole run.
- The intermediate gitleaks report file (which also holds raw secret
  values) is deleted right after its contents are read into memory.
- Cleanup runs inside `try/finally` at both the per-repo and whole-run
  level, so it still executes even if the script errors out or is
  interrupted.
- On Windows, `.git/objects` files are sometimes read-only, which can make
  a normal delete silently fail and leave folders behind — the script
  clears that flag first so cleanup completes reliably.
- Pass `--keep-clones` if you deliberately want the working copy left on
  disk afterward; you're responsible for deleting it yourself in that case.

---

## Notes

- Runs entirely on your own machine — no data sent anywhere except: (a)
  GitHub API/clone (standard), (b) Gemini API only if you run `doc_scan.py`.
- Rate limits: unauthenticated GitHub API calls are capped at 60/hr; use
  `--token` / `GITHUB_TOKEN` to raise this to 5000/hr.
- Large repos take longer to clone/scan — this does full-history clones by
  design, since that's where old leaked secrets hide.
- Findings — including the real secret value — print to your terminal.
  Don't paste that output somewhere public.
- This tool only scans repos owned by the usernames you pass to `--users`.
  It has no feature to scan an arbitrary user's account, and shouldn't be
  modified to do so — running it against accounts you don't own or haven't
  been authorized to audit is a misuse of the tool.
