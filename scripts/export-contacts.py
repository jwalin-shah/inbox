#!/usr/bin/env python3
"""Export contacts to CSV from Gmail + AddressBook."""

import csv
import json
import os
import subprocess
from pathlib import Path
from collections import defaultdict

OUTPUT_FILE = Path.home() / "contacts.csv"

def get_gmail_contacts(token):
    """Fetch all contacts from Gmail People API."""
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {token}",
         "http://127.0.0.1:9849/gmail/contacts"],
        capture_output=True, text=True
    )
    try:
        return json.loads(result.stdout) or []
    except:
        return []

def get_addressbook_contacts():
    """Fetch contacts from macOS AddressBook (via inbox server)."""
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {os.environ.get('INBOX_SERVER_TOKEN')}",
         "http://127.0.0.1:9849/contacts/search?q=*"],
        capture_output=True, text=True
    )
    try:
        return json.loads(result.stdout) or []
    except:
        return []

def merge_contacts(gmail_contacts, addressbook_contacts):
    """Merge contacts, dedup by email/phone, prioritize recent interactions."""
    merged = {}

    # Add Gmail contacts
    for contact in gmail_contacts:
        email = contact.get("email", "").lower()
        if email:
            merged[email] = {
                "name": contact.get("name", ""),
                "email": email,
                "phone": "",
                "source": "gmail",
                "last_contact": contact.get("last_message_date", ""),
            }

    # Add AddressBook contacts (fill gaps)
    for contact in addressbook_contacts:
        email = contact.get("email", "").lower()
        phone = contact.get("phone", "")

        if email and email in merged:
            # Enhance existing Gmail contact
            if phone and not merged[email]["phone"]:
                merged[email]["phone"] = phone
            merged[email]["source"] = "gmail+addressbook"
        else:
            # New contact from AddressBook
            merged[email or phone] = {
                "name": contact.get("name", ""),
                "email": email,
                "phone": phone,
                "source": "addressbook",
                "last_contact": "",
            }

    return merged

def write_csv(contacts):
    """Write contacts to CSV."""
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "email", "phone", "source", "last_contact", "notes"
        ])
        writer.writeheader()

        for key, contact in sorted(contacts.items()):
            if contact["email"] or contact["phone"]:
                writer.writerow({
                    "name": contact["name"],
                    "email": contact["email"],
                    "phone": contact["phone"],
                    "source": contact["source"],
                    "last_contact": contact["last_contact"],
                    "notes": "",
                })

def main():
    import os
    token = os.environ.get("INBOX_SERVER_TOKEN")
    if not token:
        print("❌ INBOX_SERVER_TOKEN not set")
        exit(1)

    print("Exporting contacts...")
    gmail = get_gmail_contacts(token)
    addressbook = get_addressbook_contacts()

    print(f"  Gmail: {len(gmail)} contacts")
    print(f"  AddressBook: {len(addressbook)} contacts")

    merged = merge_contacts(gmail, addressbook)
    write_csv(merged)

    print(f"✓ Exported {len(merged)} unique contacts to {OUTPUT_FILE}")
    print(f"\nColumns: name, email, phone, source, last_contact, notes")
    print(f"You can edit the 'notes' column to add relationship metadata")

if __name__ == "__main__":
    main()
