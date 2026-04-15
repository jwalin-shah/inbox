#!/usr/bin/env python
"""Smart email organization: create labels and auto-tag emails."""

import sys

from services import (
    gmail_batch_modify,
    gmail_label_create,
    gmail_labels,
    gmail_search,
    google_auth_all,
)

LABEL_CONFIG = {
    "Newsletters": {
        "query": 'newsletter OR digest OR "weekly digest" OR "daily digest" OR "product hunt"',
        "visibility": "labelShow",
    },
    "Finance": {
        "query": "invoice OR receipt OR payment OR transaction OR statement OR billing OR tax OR "
        '"credit card" OR "bank statement"',
        "visibility": "labelShow",
    },
    "Jobs": {
        "query": '"job opportunity" OR interview OR LinkedIn OR hiring OR recruiter OR "career" OR "apply now" OR "job opening"',
        "visibility": "labelShow",
    },
    "Promotions": {
        "query": "CATEGORY_PROMOTIONS OR deal OR offer OR discount OR promo OR coupon OR sale OR "
        '"special offer" OR "limited time"',
        "visibility": "labelShow",
    },
}


def main():
    """Organize inbox by tagging emails with smart labels."""
    # Auth
    gmail_svcs, _, _, _, _ = google_auth_all()
    if not gmail_svcs:
        print("ERROR: No Gmail accounts authenticated")
        return 1

    service = list(gmail_svcs.values())[0]
    account = list(gmail_svcs.keys())[0]

    print(f"Using account: {account}")
    print()

    # Get/create labels
    existing_labels = {label["name"]: label["id"] for label in gmail_labels(service)}
    labels_to_use = {}

    for label_name, config in LABEL_CONFIG.items():
        if label_name in existing_labels:
            labels_to_use[label_name] = existing_labels[label_name]
            print(f"✓ Label '{label_name}' exists (ID: {labels_to_use[label_name]})")
        else:
            try:
                result = gmail_label_create(service, label_name, config["visibility"])
                labels_to_use[label_name] = result["id"]
                print(f"✓ Created label '{label_name}' (ID: {result['id']})")
            except Exception as e:
                print(f"✗ Failed to create label '{label_name}': {e}")

    # Tag emails by category
    print("\nScanning and tagging emails...")
    stats = {label: 0 for label in labels_to_use}

    for label_name, label_id in labels_to_use.items():
        config = LABEL_CONFIG[label_name]
        query = config["query"]

        # Search for emails matching this category
        try:
            conversations = gmail_search(service, account, q=query, limit=1000)
            if not conversations:
                print(f"  {label_name}: 0 emails found")
                continue

            # Get message IDs (extract from message_id)
            msg_ids = []
            for conv in conversations:
                if conv.get("message_id"):
                    msg_ids.append(conv["message_id"])

            if msg_ids:
                # Batch apply label
                success = gmail_batch_modify(
                    service,
                    msg_ids,
                    add_label_ids=[label_id],
                    remove_label_ids=[],
                )
                if success:
                    stats[label_name] = len(msg_ids)
                    print(f"  {label_name}: Tagged {len(msg_ids)} emails ✓")
                else:
                    print(f"  {label_name}: Failed to tag emails ✗")
        except Exception as e:
            print(f"  {label_name}: Error — {e}")

    print("\n=== Summary ===")
    total = sum(stats.values())
    for label, count in sorted(stats.items()):
        print(f"{label}: {count}")
    print(f"Total emails tagged: {total}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
