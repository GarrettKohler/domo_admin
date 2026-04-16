#!/usr/bin/env python3
"""Generate ready-to-send cleanup emails from the template and rollout manifest.

Reads the email template and rollout manifest, fills in placeholders for each
owner, and writes individual .eml files to output/cleanup_emails/.

Usage:
    python3 generate_cleanup_emails.py              # Generate all emails
    python3 generate_cleanup_emails.py --preview     # Print first email to stdout
    python3 generate_cleanup_emails.py --owner "Aaron Olson"  # Single owner
"""

import argparse
import csv
import os
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
TEMPLATE_PATH = OUTPUT_DIR / "cleanup_email_template.md"
MANIFEST_PATH = OUTPUT_DIR / "rollout_manifest.csv"
EMAILS_DIR = OUTPUT_DIR / "cleanup_emails"

# Email metadata
FROM_NAME = "Aaron Olson"
FROM_EMAIL = "aaron.olson@gstv.com"
CC_ESCALATION = "garrett.kohler@gstv.com, sriram.vepuri@gstv.com"


def load_template() -> str:
    """Load the email template."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        content = f.read()

    # Strip the subject line and separators — we'll handle subject separately
    lines = content.strip().split("\n")
    # Find the body (after first "---" separator)
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            body_start = i + 1
            break

    # Find the end (before last "---" separator or attachment line)
    body_end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            body_end = i
            break

    body = "\n".join(lines[body_start:body_end]).strip()
    return body


def load_manifest() -> list[dict]:
    """Load the rollout manifest."""
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sanitize_filename(name: str) -> str:
    """Convert owner name to a safe filename."""
    return re.sub(r'[^\w\-]', '_', name).strip('_')


def _friendly_name(owner_name: str) -> str:
    """Get a friendly greeting name from an owner name."""
    if not owner_name:
        return "Team"
    # Service accounts and special groups get a friendly override
    lower = owner_name.lower()
    if "domo-admin" in lower or "domo admin" in lower:
        return "Garrett and Sriram"
    if "former" in lower or "data team" in lower:
        return "Garrett and Sriram"
    # Normal people: use first name
    return owner_name.split()[0]


def fill_template(template: str, owner: dict) -> str:
    """Fill in template placeholders for a specific owner."""
    owner_name = owner.get("Owner", "").strip()
    greeting_name = _friendly_name(owner_name)
    total = owner.get("Total Items for Review", "0")
    datasets = owner.get("Datasets Flagged", "0")
    dataflows = owner.get("Dataflows Flagged", "0")

    body = template
    body = body.replace("{Owner Name}", greeting_name)
    body = body.replace("{Total Items}", str(total))
    body = body.replace("{Dataset Count}", str(datasets))
    body = body.replace("{Dataflow Count}", str(dataflows))

    return body


def build_eml(owner_name: str, owner_email: str, subject: str, body: str, attachment_name: str) -> str:
    """Build a .eml file content (RFC 2822 format)."""
    first_name = owner_name.split()[0] if owner_name else "Team"

    eml = f"""From: {FROM_NAME} <{FROM_EMAIL}>
To: {owner_name} <{owner_email}>
Cc: {CC_ESCALATION}
Subject: {subject}
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

{body}

---
Attachment: {attachment_name}
(Attach the file from output/owner_rollouts/ before sending)
"""
    return eml


def generate_emails(owners: list[dict], template: str, preview: bool = False) -> int:
    """Generate .eml files for all owners."""
    if not preview:
        EMAILS_DIR.mkdir(parents=True, exist_ok=True)

    subject = "Action Required by May 1: Domo Dataset & Dataflow Cleanup Review"
    count = 0

    for owner in owners:
        owner_name = owner.get("Owner", "").strip()
        if not owner_name:
            continue

        spreadsheet = owner.get("Spreadsheet", "").strip()
        body = fill_template(template, owner)

        # Guess email from name (lowercase first.last@gstv.com)
        # This is a placeholder — update with real emails before sending
        name_parts = owner_name.lower().replace("-", " ").split()
        if len(name_parts) >= 2:
            email_guess = f"{name_parts[0]}.{name_parts[-1]}@gstv.com"
        else:
            email_guess = f"{name_parts[0]}@gstv.com"

        # For service accounts, adjust
        if "domo-admin" in owner_name.lower() or "former" in owner_name.lower():
            email_guess = "garrett.kohler@gstv.com"

        attachment_name = spreadsheet if spreadsheet else f"cleanup_review_{sanitize_filename(owner_name)}.xlsx"

        eml_content = build_eml(owner_name, email_guess, subject, body, attachment_name)

        if preview:
            print(f"\n{'=' * 70}")
            print(f"TO: {owner_name} <{email_guess}>")
            print(f"ITEMS: {owner.get('Total Items for Review', '?')}")
            print(f"ATTACHMENT: {attachment_name}")
            print(f"{'=' * 70}")
            print(body[:500])
            if len(body) > 500:
                print(f"\n... ({len(body)} chars total)")
            print()
        else:
            filename = f"cleanup_email_{sanitize_filename(owner_name)}.eml"
            eml_path = EMAILS_DIR / filename
            with open(eml_path, "w", encoding="utf-8") as f:
                f.write(eml_content)
            count += 1

    return count


def main():
    parser = argparse.ArgumentParser(description="Generate cleanup emails from template and manifest")
    parser.add_argument("--preview", action="store_true",
                        help="Print emails to stdout instead of writing files")
    parser.add_argument("--owner", type=str, default=None,
                        help="Generate email for a single owner only")
    args = parser.parse_args()

    if not TEMPLATE_PATH.exists():
        print(f"Error: Template not found: {TEMPLATE_PATH}")
        sys.exit(1)
    if not MANIFEST_PATH.exists():
        print(f"Error: Manifest not found: {MANIFEST_PATH}")
        sys.exit(1)

    template = load_template()
    owners = load_manifest()

    if args.owner:
        owners = [o for o in owners if args.owner.lower() in o.get("Owner", "").lower()]
        if not owners:
            print(f"No owner matching '{args.owner}' found in manifest.")
            sys.exit(1)

    if args.preview:
        generate_emails(owners, template, preview=True)
    else:
        count = generate_emails(owners, template, preview=False)
        print(f"\n{'=' * 60}")
        print("CLEANUP EMAILS GENERATED")
        print(f"{'=' * 60}")
        print(f"  Emails created: {count}")
        print(f"  Output:         {EMAILS_DIR}/")
        print()
        print("BEFORE SENDING:")
        print("  1. Review each .eml file for accuracy")
        print("  2. Update email addresses (currently guessed from names)")
        print("  3. Attach the matching spreadsheet from output/owner_rollouts/")
        print("  4. Send from your email client")
        print()
        print("  Or import .eml files directly into Outlook/Gmail.")


if __name__ == "__main__":
    main()
