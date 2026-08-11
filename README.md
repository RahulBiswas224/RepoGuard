# Self Audit Scanner

Scan **your own** public GitHub repos (across any number of accounts you personally
own) for accidentally leaked secrets — including secrets buried in old or
"deleted" commits that are still sitting in git history.

This is meant for auditing yourself, not other people's accounts.

## What it does

1. `self_audit.py` — pulls the list of your public repos via the GitHub API,
   clones each with **full history**, and runs [gitleaks](https://github.com/gitleaks/gitleaks)
   against the entire commit history (not just the latest snapshot) to catch
   secrets even if you deleted them in a later commit.
2. `doc_scan.py` (optional) — finds PDFs/docx in a cloned repo and uses Gemini
   to check them for sensitive content that gitleaks can't catch (PII, pasted
   credentials in prose, confidential markers, etc.).

## Setup

```bash
# 1. Install gitleaks
brew install gitleaks   # macOS
# or download a release binary: https://github.com/gitleaks/gitleaks/releases

# 2. Install python deps (only needed for doc_scan.py)
pip install google-generativeai pypdf python-docx

# 3. (recommended) create a GitHub personal access token
# https://github.com/settings/tokens — no special scopes needed for public repo reads,
# it just raises your rate limit from 60/hr to 5000/hr
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# 4. (optional, for doc_scan.py) get a Gemini API key
# https://aistudio.google.com/apikey
export GEMINI_API_KEY=xxxxxxxxxxxx
```

## Usage

### Scan all your accounts for leaked secrets (main tool)

```bash
python3 self_audit.py --users your-username your-other-username --output report.json
```

This will:
- List every public repo for each username
- Clone each one (full history) into a temp dir
- Run gitleaks against the whole history
- Delete the clones when done (unless `--keep-clones` is passed)
- Write a summary report to `report.json`

Example output:
```
=== Auditing GitHub user: your-username ===
Found 12 public repos
  -> Scanning your-username/old-project ...
     SECRETS_FOUND (1 finding(s))
  -> Scanning your-username/new-project ...
     clean (0 finding(s))
...
DONE. Total findings: 1 across 1 repo(s).
Full report written to: report.json

Repos needing attention:
  - your-username/old-project: 1 finding(s)
```

The report itself has secret **values redacted** (gitleaks `--redact` flag) —
it tells you *which file, which commit, which rule matched*, not the actual
key, so the report itself is safe to store/share with e.g. a teammate helping
you rotate keys.

### If something is found

1. **Rotate/revoke the leaked credential immediately** — assume it's
   compromised the moment it hit a public repo, regardless of how long ago.
2. To actually remove it from history (optional, but good practice), use
   [git-filter-repo](https://github.com/newren/git-filter-repo) or BFG Repo-Cleaner,
   then force-push. Note this rewrites history and anyone who cloned before
   needs to re-clone.

### Scan documents in a specific repo for sensitive content

```bash
python3 self_audit.py --users your-username --keep-clones --workdir ./clones
python3 doc_scan.py ./clones/your-username/some-repo
```

## Notes

- Runs entirely on your own machine — no data sent anywhere except: (a) GitHub
  API/clone (standard), (b) Gemini API only if you run `doc_scan.py`.
- Rate limits: unauthenticated GitHub API calls are capped at 60/hr; use
  `--token` / `GITHUB_TOKEN` to raise this to 5000/hr.
- Large repos will take longer to clone/scan — this does full-history clones
  by design, since that's where old leaked secrets hide.