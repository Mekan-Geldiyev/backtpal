import os
import requests
from typing import Optional, Dict, Any
from datetime import datetime


class NotionTradeLogger:
    """Integrates with Notion API to log trades to your journal database."""

    def __init__(self, api_token: str, database_id: str):
        """
        Initialize Notion integration.

        Args:
            api_token: Notion API token (starts with 'ntn_')
            database_id: The ID of your Trader's Master Journal database
        """
        self.api_token = api_token
        self.database_id = database_id
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    def add_trade(
        self,
        description: str,
        symbol: Optional[str] = None,
        account: Optional[str] = None,
        model: Optional[str] = None,
        session: Optional[str] = None,
        entry_timeframe: Optional[str] = None,
        screenshots: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Add a new trade entry to your Notion journal.

        Args:
            description: Trade description (captured from voice)
            symbol: Trading symbol/instrument (e.g., "EURUSD")
            account: Trading account name
            model: Trading model/strategy
            session: Trading session (e.g., "London", "New York")
            entry_timeframe: Timeframe (e.g., "1H", "4H", "1D")
            screenshots: List of screenshot file paths to attach

        Returns:
            Response from Notion API with the created page details
        """
        properties = {
            "Lesson Learned": {
                "rich_text": [{"type": "text", "text": {"content": description}}]
            },
            "Status": {"status": {"name": "Open"}},
        }

        # Add optional fields if provided
        if symbol:
            properties["Symbol"] = {
                "rich_text": [{"type": "text", "text": {"content": symbol}}]
            }

        if account:
            properties["Account"] = {
                "rich_text": [{"type": "text", "text": {"content": account}}]
            }

        if model:
            properties["Model"] = {
                "rich_text": [{"type": "text", "text": {"content": model}}]
            }

        if session:
            properties["Session"] = {
                "rich_text": [{"type": "text", "text": {"content": session}}]
            }

        if entry_timeframe:
            properties["Entry TimeFrame"] = {
                "rich_text": [{"type": "text", "text": {"content": entry_timeframe}}]
            }

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            response = requests.post(
                f"{self.base_url}/pages",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            print("✓ Trade successfully added to Notion")
            return response.json()
        except requests.exceptions.RequestException as exc:
            print(f"✗ Failed to add trade to Notion: {exc}")
            raise

    def update_trade(
        self, page_id: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update an existing trade entry.

        Args:
            page_id: The Notion page ID of the trade
            updates: Dictionary of property updates

        Returns:
            Updated page details from Notion
        """
        properties = {}

        for key, value in updates.items():
            if isinstance(value, str):
                properties[key] = {
                    "rich_text": [{"type": "text", "text": {"content": value}}]
                }
            elif isinstance(value, (int, float)):
                properties[key] = {"number": value}
            else:
                properties[key] = value

        payload = {"properties": properties}

        try:
            response = requests.patch(
                f"{self.base_url}/pages/{page_id}",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            print("✓ Trade updated in Notion")
            return response.json()
        except requests.exceptions.RequestException as exc:
            print(f"✗ Failed to update trade: {exc}")
            raise


def load_notion_credentials() -> tuple[str, str]:
    """
    Load Notion API credentials from environment or config.

    Returns:
        Tuple of (api_token, database_id)
    """
    api_token = os.getenv("NOTION_API_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not api_token or not database_id:
        raise ValueError(
            "Please set NOTION_API_TOKEN and NOTION_DATABASE_ID environment variables."
        )

    return api_token, database_id
