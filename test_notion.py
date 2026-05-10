"""Test script for Notion integration against the Trades database.

This script creates a new row in the Trades database (not a child page under
the journal page), so it appears in your existing Trades list view.
"""

import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

NOTION_VERSION = "2022-06-28"


def build_headers(api_token: str) -> dict:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def is_valid_uuidish(raw_id: str) -> bool:
    clean = raw_id.replace("-", "")
    return len(clean) == 32 and all(c in "0123456789abcdefABCDEF" for c in clean)


def find_trades_database(api_token: str) -> tuple[str, str]:
    """Return (database_id, database_title) for the best matching Trades DB."""
    headers = build_headers(api_token)
    payload = {
        "query": "Trades",
        "filter": {"property": "object", "value": "database"},
        "page_size": 100,
    }

    response = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json=payload,
        timeout=15,
    )
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        raise RuntimeError(
            "No databases were found. Make sure your integration is connected to the workspace."
        )

    def db_title(db: dict) -> str:
        title_parts = db.get("title", [])
        return "".join(part.get("plain_text", "") for part in title_parts).strip()

    scored = []
    exact_match = None
    for db in results:
        title = db_title(db)
        lower = title.lower()
        score = 0
        if lower == "trades":
            score += 100
            exact_match = (db.get("id", ""), title)
        if "trade" in lower:
            score += 10
        scored.append((score, db.get("id", ""), title))

    if exact_match and exact_match[0]:
        return exact_match[0], exact_match[1]

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:5]
    candidates = ", ".join(
        f"{title or 'Untitled'} ({db_id})" for _, db_id, title in top if db_id
    )
    raise RuntimeError(
        "Could not find an exact database named 'Trades'. "
        "Set NOTION_TRADES_DATABASE_ID in .env to the correct ID. "
        f"Top matches: {candidates}"
    )


def get_title_property_name(api_token: str, database_id: str) -> str:
    """Find the title property key for the database schema."""
    headers = build_headers(api_token)
    response = requests.get(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()

    properties = response.json().get("properties", {})
    for prop_name, prop_meta in properties.items():
        if prop_meta.get("type") == "title":
            return prop_name

    raise RuntimeError("No title property found in the Trades database schema.")


def get_database_properties(api_token: str, database_id: str) -> dict:
    """Fetch and return the database property schema."""
    headers = build_headers(api_token)
    response = requests.get(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("properties", {})


def find_property_name(properties: dict, candidates: list[str]) -> str | None:
    """Find a property by exact or partial case-insensitive name."""
    lowered = {name.lower(): name for name in properties.keys()}

    for candidate in candidates:
        exact = lowered.get(candidate.lower())
        if exact:
            return exact

    for candidate in candidates:
        cand_lower = candidate.lower()
        for existing_lower, original_name in lowered.items():
            if cand_lower in existing_lower:
                return original_name

    return None


def build_property_update(prop_meta: dict, value: str, today_date: str | None = None) -> dict | None:
    """Build a valid Notion property payload based on property type."""
    prop_type = prop_meta.get("type")

    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": value}}]}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": value}}]}
    if prop_type == "select":
        return {"select": {"name": value}}
    if prop_type == "multi_select":
        return {"multi_select": [{"name": value}]}
    if prop_type == "status":
        return {"status": {"name": value}}
    if prop_type == "date":
        return {"date": {"start": today_date or value}}

    return None


def find_page_by_title(api_token: str, database_id: str, title_text: str) -> str | None:
    """Find a page ID in a database by exact title text."""
    headers = build_headers(api_token)
    properties = get_database_properties(api_token, database_id)

    title_property = None
    for name, meta in properties.items():
        if meta.get("type") == "title":
            title_property = name
            break

    if not title_property:
        return None

    payload = {
        "filter": {
            "property": title_property,
            "title": {"equals": title_text},
        },
        "page_size": 1,
    }
    response = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=headers,
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if results:
        return results[0].get("id")
    return None


def ensure_relation_page(api_token: str, relation_db_id: str, title_text: str) -> str:
    """Find or create a related page and return its ID."""
    existing = find_page_by_title(api_token, relation_db_id, title_text)
    if existing:
        return existing

    title_property = get_title_property_name(api_token, relation_db_id)
    created = create_trade_row(
        api_token=api_token,
        database_id=relation_db_id,
        title_property=title_property,
        trade_title=title_text,
        extra_properties={},
    )
    created_id = created.get("id")
    if not created_id:
        raise RuntimeError(f"Failed to create related page '{title_text}'.")
    return created_id


def build_relation_update(api_token: str, prop_meta: dict, value: str) -> dict:
    """Build relation payload by resolving/creating the related row."""
    relation_info = prop_meta.get("relation", {})
    relation_db_id = relation_info.get("database_id")
    if not relation_db_id:
        raise RuntimeError("Relation property is missing database_id.")

    related_page_id = ensure_relation_page(api_token, relation_db_id, value)
    return {"relation": [{"id": related_page_id}]}


def create_trade_row(
    api_token: str,
    database_id: str,
    title_property: str,
    trade_title: str,
    extra_properties: dict,
) -> dict:
    """Create one page row in the selected Trades database."""
    headers = build_headers(api_token)

    row_properties = {
        title_property: {
            "title": [{"type": "text", "text": {"content": trade_title}}]
        }
    }
    row_properties.update(extra_properties)

    payload = {
        "parent": {"database_id": database_id},
        "properties": row_properties,
    }

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=headers,
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def test_notion_connection():
    """Test Notion API connection and Trades database row creation."""
    print("=" * 60)
    print("BackTPal Notion Integration Test")
    print("=" * 60)

    # Check environment variables
    api_token = os.getenv("NOTION_API_TOKEN")
    configured_database_id = os.getenv("NOTION_TRADES_DATABASE_ID", "").strip()

    print("\n1. Checking environment variables...")
    if not api_token:
        print("   ✗ NOTION_API_TOKEN not set in .env")
        return False
    else:
        masked_token = api_token[:10] + "..." + api_token[-5:]
        print(f"   ✓ NOTION_API_TOKEN found: {masked_token}")

    if configured_database_id:
        print(f"   ✓ NOTION_TRADES_DATABASE_ID found: {configured_database_id}")
    else:
        print("   ! NOTION_TRADES_DATABASE_ID not set (will auto-discover Trades DB)")

    print("\n2. Resolving Trades database...")
    try:
        if configured_database_id:
            if not is_valid_uuidish(configured_database_id):
                print("   ✗ NOTION_TRADES_DATABASE_ID format is invalid")
                return False
            database_id = configured_database_id
            database_title = "Configured Database"
        else:
            database_id, database_title = find_trades_database(api_token)

        print(f"   ✓ Using database: {database_title}")
        print(f"   ✓ Database ID: {database_id}")
    except Exception as exc:
        print(f"   ✗ Failed to resolve Trades database: {exc}")
        return False

    print("\n3. Reading database schema...")
    try:
        title_property = get_title_property_name(api_token, database_id)
        db_properties = get_database_properties(api_token, database_id)
        print(f"   ✓ Title property: {title_property}")
    except Exception as exc:
        print(f"   ✗ Failed to read database schema: {exc}")
        return False

    today_date = datetime.now().strftime("%Y-%m-%d")
    fillers = {
        "account": "integrationtest",
        "model": "s/r",
        "symbol": "MNQ!",
        "entry_exit_date": today_date,
        "why": "Integration test entry: validating Notion row creation from BackTPal.",
    }

    prop_candidates = {
        "account": ["Account"],
        "model": ["Model"],
        "symbol": ["Symbol"],
        "entry_exit_date": ["Entry / Exit Date", "Entry/Exit Date", "Entry Exit Date", "Entry Date"],
        "why": ["Why I took this trade", "Why I Took This Trade", "Why", "Notes"],
    }

    extra_properties = {}
    print("\n   Filling requested fields when present in schema...")
    for key, candidates in prop_candidates.items():
        prop_name = find_property_name(db_properties, candidates)
        if not prop_name:
            print(f"   ! Skipped {key}: property not found")
            continue

        prop_meta = db_properties[prop_name]
        prop_type = prop_meta.get("type", "unknown")
        if prop_type == "relation":
            try:
                update_payload = build_relation_update(api_token, prop_meta, fillers[key])
            except Exception as exc:
                print(f"   ! Skipped {prop_name}: relation setup failed ({exc})")
                continue
        else:
            update_payload = build_property_update(
                prop_meta,
                fillers[key],
                today_date=today_date,
            )

        if not update_payload:
            print(f"   ! Skipped {prop_name}: unsupported type '{prop_type}'")
            continue

        extra_properties[prop_name] = update_payload
        print(f"   ✓ {prop_name} filled")

    print("\n4. Attempting to create a test trade row in Trades database...")
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_trade_name = f"BackTPal API test - {stamp}"

        result = create_trade_row(
            api_token=api_token,
            database_id=database_id,
            title_property=title_property,
            trade_title=test_trade_name,
            extra_properties=extra_properties,
        )

        print("   ✓ Trade row created successfully!")

        page_id = result.get("id", "N/A")
        notion_url = result.get("url", "N/A")
        created_time = result.get("created_time", "N/A")

        print("\n   Page Details:")
        print(f"      Page ID: {page_id}")
        print(f"      Created: {created_time}")
        print(f"      URL: {notion_url}")
        print(f"\n   Open this row: {notion_url}")

        return True
    except Exception as exc:
        print(f"   ✗ Failed to create trade row: {exc}")
        return False


if __name__ == "__main__":
    success = test_notion_connection()
    print("\n" + "=" * 60)
    if success:
        print("✓ All tests passed! Trades database integration is working.")
        print("\nYou can now run: python transcribe_live.py")
        sys.exit(0)
    else:
        print("✗ Some tests failed. Check your .env file.")
        print("\nFix the issues above and run this script again.")
        sys.exit(1)
