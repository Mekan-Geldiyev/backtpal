"""
Find your Notion database IDs.
This script queries Notion to list all accessible databases.

Usage:
    python find_notion_database.py
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

api_token = os.getenv("NOTION_API_TOKEN")

if not api_token:
    print("✗ NOTION_API_TOKEN not set in .env")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

print("=" * 70)
print("Notion Database Finder")
print("=" * 70)
print("\nSearching for accessible databases and tables...\n")

try:
    # Query for databases
    response = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json={"filter": {"value": "database", "property": "object"}},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json()

    databases = results.get("results", [])

    if not databases:
        print("✗ No databases found. Make sure you've added the BackTPal integration")
        print("  to your Notion workspace in: https://www.notion.so/my-integrations")
        sys.exit(1)

    print(f"Found {len(databases)} database(s):\n")

    for i, db in enumerate(databases, 1):
        db_id = db.get("id", "").replace("-", "")
        
        # Handle title safely
        title_list = db.get("title", [])
        if title_list and isinstance(title_list, list):
            db_name = title_list[0].get("plain_text", "Untitled") if isinstance(title_list[0], dict) else "Untitled"
        else:
            db_name = "Untitled"
        
        print(f"{i}. {db_name}")
        print(f"   ID: {db_id}")
        print(f"   Full ID with dashes: {db.get('id', 'N/A')}")
        print()

    print("=" * 70)
    print("Copy the database ID (without dashes) into your .env file:")
    print("  NOTION_DATABASE_ID=<id_from_above>")
    print("=" * 70)

except requests.exceptions.RequestException as exc:
    print(f"✗ Failed to query Notion: {exc}")
    print("\nMake sure:")
    print("  1. NOTION_API_TOKEN is correct in .env")
    print("  2. You've shared the BackTPal integration with your Notion workspace")
    sys.exit(1)
