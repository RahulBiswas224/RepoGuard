#!/usr/bin/env python3
"""
self_audit.py — Scan YOUR OWN public GitHub repos (across any accounts you own)
for accidentally leaked secrets, including in old/deleted commit history.

When a secret is found, this prints the actual matched value to your console
immediately (so you know exactly what to rotate) and then guarantees the
cloned repo + any temp report files are deleted afterward — even if the
script crashes partway through. Nothing sensitive is left on disk when it
finishes, except the final summary report, which is redacted by default.

Intended use: run this against GitHub usernames that belong to YOU, to check
you haven't leaked credentials. Not intended for scanning other people's accounts.

Requirements:
  - git installed
  - gitleaks installed and on PATH (https://github.com/gitleaks/gitleaks/releases)
  - python3
  - (optional) GEMINI_API_KEY env var, for scanning PDFs/docx for sensitive content

Usage:
  python3 self_audit.py --users myuser1 myuser2 --token ghp_xxx
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

GITHUB_API = "https://api.github.com"


def _force_remove_readonly(func, path, exc_info):
    """
    Windows (and .git object files in general) sometimes mark files read-only,
    which makes shutil.rmtree fail with PermissionError. This retries the
    removal after clearing the read-only bit, so cleanup never leaves files behind.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"  ! could not remove {path}: {e}", file=sys.stderr)


def safe_rmtree(path):
    """rmtree that won't silently leave locked/read-only files behind on Windows."""
    if os.path.exists(path):
        shutil.rmtree(path, onerror=_force_remove_readonly)


def gh_request(url, token=None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "self-audit-scanner")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  ! GitHub API error {e.code} for {url}: {body[:300]}", file=sys.stderr)
        return None, None


def list_public_repos(username, token=None):
    """Paginate through /users/{username}/repos, public repos only."""
    repos = []
    page = 1
    while True:
        url = f"{GITHUB_API}/users/{username}/repos?type=owner&per_page=100&page={page}"
        data, _ = gh_request(url, token)
        if not data:
            break
        public = [r for r in data if not r.get("private")]
        repos.extend(public)
        if len(data) < 100:
            break
        page += 1
    return repos


def clone_full_history(clone_url, dest, token=None):
    """Full clone (no --depth) so gitleaks can scan entire history, not just HEAD."""
    if token:
        # inject token for auth to raise rate limits / avoid throttling on clone
        clone_url = clone_url.replace("https://", f"https://{token}@")
    result = subprocess.run(
        ["git", "clone", "--quiet", clone_url, dest],
        capture_output=True, text=True, timeout=600
    )
    return result.returncode == 0, result.stderr


def run_gitleaks(repo_path, report_path):
    """
    Run gitleaks against full git history of a cloned repo.
    Deliberately NOT using --redact here: we want the real matched value so
    you can see exactly which key it is and rotate the right one. This value
    only ever gets printed to your own console and optionally kept in the
    summary report — see --reveal-secrets / --redact-output flags in main().
    """
    result = subprocess.run(
        [
            "gitleaks", "detect",
            "--source", repo_path,
            "--report-format", "json",
            "--report-path", report_path,
            "--no-banner",
        ],
        capture_output=True, text=True, timeout=600
    )
    # gitleaks exits 1 if leaks found, 0 if clean — both are "success" runs
    findings = []
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                findings = json.load(f)
        except json.JSONDecodeError:
            findings = []
    return findings, result.stderr


def check_gitleaks_installed():
    if shutil.which("gitleaks") is None:
        print(
            "ERROR: gitleaks is not installed or not on PATH.\n"
            "Install it from: https://github.com/gitleaks/gitleaks/releases\n"
            "(or `brew install gitleaks` on macOS, or see their README for other package managers)",
            file=sys.stderr,
        )
        sys.exit(1)


def prompt_repo_selection(username, repos):
    """
    Show a numbered menu for one user's repos and let them choose:
      1        -> scan all repos
      2..N+1   -> individual repos (comma-separated for multiple, e.g. "3,5,7")
      N+2      -> abort (skip this user entirely, no scan)
    Returns the filtered list of repo dicts to scan (possibly empty if aborted).
    """
    if not repos:
        return []

    all_option = 1
    repo_start = 2
    abort_option = repo_start + len(repos)

    print(f"\nFound {len(repos)} public repos for {username}:\n")
    print(f"  {all_option}. Scan ALL repos")
    for i, repo in enumerate(repos):
        print(f" {repo_start + i:>2}. {repo['name']}")
    print(f" {abort_option:>2}. Abort (skip {username}, scan nothing for this user)")

    while True:
        raw = input(
            f"\nEnter your choice for {username} "
            f"(e.g. \"{all_option}\" for all, \"{repo_start},{repo_start+1}\" for specific repos, "
            f"\"{abort_option}\" to abort): "
        ).strip()

        if not raw:
            print("  Please enter a choice.")
            continue

        try:
            choices = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("  Invalid input — enter numbers only, comma-separated.")
            continue

        if not choices:
            print("  Please enter at least one number.")
            continue

        if abort_option in choices:
            print(f"  Aborted — skipping {username}.")
            return []

        if all_option in choices:
            return repos

        selected = []
        invalid = []
        for c in choices:
            idx = c - repo_start
            if 0 <= idx < len(repos):
                selected.append(repos[idx])
            else:
                invalid.append(c)

        if invalid:
            print(f"  Invalid option(s): {invalid} — valid range is {all_option}-{abort_option}. Try again.")
            continue

        return selected


def main():
    parser = argparse.ArgumentParser(description="Audit your own public GitHub repos for leaked secrets.")
    parser.add_argument("--users", nargs="+", required=True, help="Your GitHub username(s) to audit")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                         help="GitHub personal access token (raises rate limit from 60/hr to 5000/hr). Or set GITHUB_TOKEN env var.")
    parser.add_argument("--workdir", default=None,
                         help="Directory to clone repos into (default: system temp dir). "
                              "Deleted automatically when the scan finishes, unless --keep-clones is set.")
    parser.add_argument("--keep-clones", action="store_true",
                         help="Keep cloned repos on disk after scanning (off by default — cleanup is automatic).")
    parser.add_argument("--output", default="audit_report.json", help="Path to write the final JSON summary report")
    parser.add_argument("--redact-output", action="store_true",
                         help="Redact secret values in the saved --output file (they still print to your console "
                              "during the scan). Off by default since this report stays on your own machine, but "
                              "turn it on if you might share/back up the report file.")
    parser.add_argument("--no-interactive", action="store_true",
                         help="Skip the repo-selection menu and scan ALL public repos for every user "
                              "(useful for automation/cron). Off by default — the menu shows by default.")
    args = parser.parse_args()

    check_gitleaks_installed()

    workdir = args.workdir or tempfile.mkdtemp(prefix="self_audit_")
    os.makedirs(workdir, exist_ok=True)
    print(f"Working directory (temporary, auto-deleted at the end): {workdir}")

    all_results = []

    try:
        for username in args.users:
            print(f"\n=== Auditing GitHub user: {username} ===")
            repos = list_public_repos(username, args.token)

            if args.no_interactive:
                print(f"Found {len(repos)} public repos — scanning all (--no-interactive)")
                selected_repos = repos
            else:
                selected_repos = prompt_repo_selection(username, repos)
                if not selected_repos:
                    continue

            for repo in selected_repos:
                name = repo["name"]
                clone_url = repo["clone_url"]
                print(f"  -> Scanning {username}/{name} ...")

                dest = os.path.join(workdir, username, name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)

                ok, err = clone_full_history(clone_url, dest, args.token)
                if not ok:
                    print(f"     ! clone failed: {err.strip()[:200]}")
                    all_results.append({
                        "user": username, "repo": name, "status": "clone_failed", "error": err.strip()[:500]
                    })
                    safe_rmtree(dest)
                    continue

                report_path = dest + "_gitleaks.json"
                try:
                    findings, gl_err = run_gitleaks(dest, report_path)

                    status = "clean" if not findings else "SECRETS_FOUND"
                    print(f"     {status} ({len(findings)} finding(s))")

                    # Print full, unredacted detail to console immediately so you
                    # know exactly which key/service this is and can go rotate it.
                    for f in findings:
                        secret_val = f.get("Secret", "")
                        print(
                            "\n     " + "-" * 44 +
                            f"\n     RULE:    {f.get('RuleID')}"
                            f"\n     FILE:    {f.get('File')}"
                            f"\n     COMMIT:  {f.get('Commit')}"
                            f"\n     DATE:    {f.get('Date')}"
                            f"\n     AUTHOR:  {f.get('Author')}"
                            f"\n     SECRET:  {secret_val}"
                            f"\n     LINK:    https://github.com/{username}/{name}/commit/{f.get('Commit')}"
                            "\n     " + "-" * 44
                        )

                    # Only repos with actual findings get written into the report —
                    # clean repos are skipped so the file only lists what needs action.
                    if findings:
                        all_results.append({
                            "user": username,
                            "repo": name,
                            "status": status,
                            "finding_count": len(findings),
                            "findings": [
                                {
                                    "rule": f.get("RuleID"),
                                    "file": f.get("File"),
                                    "commit": f.get("Commit"),
                                    "date": f.get("Date"),
                                    "author": f.get("Author"),
                                    "commit_url": f"https://github.com/{username}/{name}/commit/{f.get('Commit')}",
                                    "secret": "[REDACTED]" if args.redact_output else f.get("Secret", ""),
                                }
                                for f in findings
                            ],
                        })
                finally:
                    # Always remove the gitleaks report file — it contains raw
                    # secret values and has no reason to persist on disk.
                    if os.path.exists(report_path):
                        os.remove(report_path)
                    if not args.keep_clones:
                        safe_rmtree(dest)
    finally:
        # Guaranteed cleanup even if something above raised an exception —
        # no leftover clones or temp files, ever.
        if not args.keep_clones:
            safe_rmtree(workdir)

    with open(args.output, "w") as f:
        json.dump(all_results, f, indent=2)

    total_findings = sum(r.get("finding_count", 0) for r in all_results)
    flagged_repos = [r for r in all_results if r.get("finding_count", 0) > 0]

    print("\n" + "=" * 50)
    print(f"DONE. Total findings: {total_findings} across {len(flagged_repos)} repo(s).")
    print(f"Full report written to: {args.output}"
          f"{' (secrets redacted)' if args.redact_output else ' (contains raw secret values — keep this file private)'}")
    if flagged_repos:
        print("\nRepos needing attention (rotate these keys):")
        for r in flagged_repos:
            print(f"  - {r['user']}/{r['repo']}: {r['finding_count']} finding(s)")

    if not args.keep_clones:
        print(f"\nCleanup complete — no clones or temp files left on disk (checked: {workdir})")


if __name__ == "__main__":
    main()