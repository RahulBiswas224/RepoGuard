#!/usr/bin/env python3
"""
doc_scan.py — Extract text from PDFs/docx found in your repos and check them
for sensitive content (PII, confidential markers, pasted credentials) using
Gemini. Complements gitleaks, which only catches pattern-shaped secrets.

Requirements:
  pip install google-generativeai pypdf python-docx

Usage:
  export GEMINI_API_KEY=your_key
  python3 doc_scan.py /path/to/cloned/repo
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCAN_PROMPT = """You are a pre-commit security and privacy reviewer. You will be given the extracted
text content of a file that a developer has committed to a GitHub repository.

Analyze the content and determine if it is safe to have in a (possibly public) repository.
Flag the file if it contains ANY of the following:

1. Credentials & secrets: API keys, passwords, tokens, private keys, connection strings, auth headers
2. Personally Identifiable Information (PII): full names + contact info combos, SSNs, government IDs,
   financial account numbers, medical info
3. Internal/confidential markers: text like "Confidential", "Internal Only", "Do Not Distribute", NDA content
4. Business-sensitive data: unreleased pricing, contracts, internal financials, customer lists, employee data
5. Infrastructure details: internal IPs, hostnames, architecture diagrams with system names, database schemas with real data

Respond ONLY in this JSON format, with no other text:

{
  "safe_to_commit": true or false,
  "risk_level": "none" | "low" | "medium" | "high" | "critical",
  "findings": [
    {
      "category": "credential | pii | confidential_marker | business_sensitive | infra_detail",
      "description": "brief description, do NOT quote the actual sensitive value",
      "excerpt_location": "e.g. page 2, paragraph 3"
    }
  ],
  "summary": "one sentence explanation of the decision"
}

Rules:
- Never reproduce the actual secret/PII value in your response, only describe it
- If uncertain, err toward flagging (risk_level at least "low")
- Ignore standard boilerplate (license text, generic placeholder examples like "your-api-key-here")

FILE CONTENT TO REVIEW:
---
{content}
---
"""


def extract_pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx_text(path):
    import docx
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def find_docs(repo_path):
    exts = {".pdf", ".docx"}
    return [p for p in Path(repo_path).rglob("*") if p.suffix.lower() in exts]


def scan_with_gemini(text, api_key):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-pro")
    prompt = SCAN_PROMPT.replace("{content}", text[:30000])  # cap size
    resp = model.generate_content(prompt)
    raw = resp.text.strip()
    # strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"safe_to_commit": None, "risk_level": "unknown", "raw_response": raw}


def main():
    parser = argparse.ArgumentParser(description="Scan PDFs/docx in a repo for sensitive content via Gemini.")
    parser.add_argument("repo_path", help="Path to a cloned repo to scan")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: set GEMINI_API_KEY env var or pass --api-key", file=sys.stderr)
        sys.exit(1)

    docs = find_docs(args.repo_path)
    if not docs:
        print("No PDF/docx files found.")
        return

    results = []
    for doc in docs:
        print(f"Scanning {doc} ...")
        try:
            if doc.suffix.lower() == ".pdf":
                text = extract_pdf_text(doc)
            else:
                text = extract_docx_text(doc)
        except Exception as e:
            print(f"  ! failed to extract text: {e}")
            continue

        if not text.strip():
            print("  (no extractable text, skipping)")
            continue

        verdict = scan_with_gemini(text, args.api_key)
        results.append({"file": str(doc), "verdict": verdict})
        print(f"  -> risk_level: {verdict.get('risk_level')}")

    out_path = "doc_scan_report.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
