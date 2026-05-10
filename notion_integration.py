import os
import re
from datetime import datetime
from typing import Any, Optional

import requests


class NotionTradeLogger:
    """Integrates with Notion API to log trades into the Trades database."""

    def __init__(self, api_token: str, database_id: str):
        self.api_token = api_token
        self.database_id = database_id.replace("-", "")
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        self._properties_cache: Optional[dict[str, Any]] = None

    def _get_database_properties(self) -> dict[str, Any]:
        if self._properties_cache is not None:
            return self._properties_cache

        response = requests.get(
            f"{self.base_url}/databases/{self.database_id}",
            headers=self.headers,
            timeout=15,
        )
        response.raise_for_status()
        self._properties_cache = response.json().get("properties", {})
        return self._properties_cache

    def _get_title_property_name(self) -> str:
        for prop_name, prop_meta in self._get_database_properties().items():
            if prop_meta.get("type") == "title":
                return prop_name
        raise RuntimeError("No title property found in the Trades database schema.")

    def _find_property_name(self, candidates: list[str]) -> Optional[str]:
        properties = self._get_database_properties()
        lowered = {name.lower(): name for name in properties.keys()}

        for candidate in candidates:
            exact = lowered.get(candidate.lower())
            if exact:
                return exact

        for candidate in candidates:
            candidate_lower = candidate.lower()
            for existing_lower, original_name in lowered.items():
                if candidate_lower in existing_lower:
                    return original_name

        return None

    def _build_scalar_property_update(
        self,
        prop_meta: dict[str, Any],
        value: Any,
    ) -> Optional[dict[str, Any]]:
        prop_type = prop_meta.get("type")

        if prop_type == "title":
            return {"title": [{"type": "text", "text": {"content": str(value)}}]}
        if prop_type == "rich_text":
            return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
        if prop_type == "select":
            return {"select": {"name": str(value)}}
        if prop_type == "multi_select":
            return {"multi_select": [{"name": str(value)}]}
        if prop_type == "status":
            return {"status": {"name": str(value)}}
        if prop_type == "date":
            return {"date": {"start": str(value)}}
        if prop_type == "number":
            return {"number": value}
        if prop_type == "checkbox":
            return {"checkbox": bool(value)}

        return None

    def _find_page_by_title(self, database_id: str, title_text: str) -> Optional[str]:
        relation_logger = NotionTradeLogger(self.api_token, database_id)
        title_property = relation_logger._get_title_property_name()
        payload = {
            "filter": {
                "property": title_property,
                "title": {"equals": title_text},
            },
            "page_size": 1,
        }
        response = requests.post(
            f"{self.base_url}/databases/{database_id}/query",
            headers=self.headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if results:
            return results[0].get("id")
        return None

    def _ensure_relation_page(self, relation_db_id: str, title_text: str) -> str:
        existing_page_id = self._find_page_by_title(relation_db_id, title_text)
        if existing_page_id:
            return existing_page_id

        relation_logger = NotionTradeLogger(self.api_token, relation_db_id)
        title_property = relation_logger._get_title_property_name()
        payload = {
            "parent": {"database_id": relation_db_id},
            "properties": {
                title_property: {
                    "title": [{"type": "text", "text": {"content": title_text}}]
                }
            },
        }
        response = requests.post(
            f"{self.base_url}/pages",
            headers=self.headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        created_id = response.json().get("id")
        if not created_id:
            raise RuntimeError(f"Failed to create relation entry '{title_text}'.")
        return created_id

    def _build_relation_update(self, prop_meta: dict[str, Any], value: str) -> dict[str, Any]:
        relation_db_id = prop_meta.get("relation", {}).get("database_id")
        if not relation_db_id:
            raise RuntimeError("Relation property is missing database_id.")
        related_page_id = self._ensure_relation_page(relation_db_id, value)
        return {"relation": [{"id": related_page_id}]}

    def _infer_trade_outcome(self, description: str) -> tuple[Optional[str], Optional[int]]:
        lowered = description.lower()
        win_count = len(re.findall(r"\b(win|won|winner)\b", lowered))
        loss_count = len(re.findall(r"\b(lose|loss|lost)\b", lowered))
        breakeven_count = len(re.findall(r"\b(breakeven|break[ -]?even)\b", lowered))

        if breakeven_count > max(win_count, loss_count):
            return "breakeven", 0
        if win_count > loss_count:
            return "win", 1
        if loss_count > win_count:
            return "loss", -1
        if breakeven_count > 0:
            return "breakeven", 0
        return None, None

    def add_trade(
        self,
        title: str,
        description: str,
        symbol: Optional[str] = None,
        account: Optional[str] = None,
        model: Optional[str] = None,
        session: Optional[str] = None,
        entry_timeframe: Optional[str] = None,
        pnl: Optional[str] = None,
        screenshots: Optional[list] = None,
    ) -> dict[str, Any]:
        del screenshots

        today_date = datetime.now().strftime("%Y-%m-%d")
        title_property = self._get_title_property_name()
        outcome_label, rr_value = self._infer_trade_outcome(pnl or description)

        field_values = {
            "account": account,
            "model": model,
            "symbol": symbol,
            "session": session,
            "entry_timeframe": entry_timeframe,
            "entry_exit_date": today_date,
            "why": description,
            "status": "Closed",
            "actual_rr_achieved": rr_value,
        }
        field_candidates = {
            "account": ["Account"],
            "model": ["Model"],
            "symbol": ["Symbol"],
            "session": ["Session"],
            "entry_timeframe": ["Entry Timeframe", "Timeframe"],
            "entry_exit_date": ["Entry / Exit Date", "Entry/Exit Date", "Entry Exit Date", "Entry Date"],
            "why": ["Why I took this trade", "Why I Took This Trade", "Why", "Notes"],
            "status": ["Status"],
            "actual_rr_achieved": ["Actual RR Achieved", "Actual RR", "RR Achieved"],
        }

        properties: dict[str, Any] = {
            title_property: {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }

        db_properties = self._get_database_properties()
        for field_key, candidates in field_candidates.items():
            value = field_values[field_key]
            if value is None or value == "":
                continue

            prop_name = self._find_property_name(candidates)
            if not prop_name:
                continue

            prop_meta = db_properties[prop_name]
            prop_type = prop_meta.get("type")
            if prop_type == "relation":
                update_payload = self._build_relation_update(prop_meta, str(value))
            else:
                update_payload = self._build_scalar_property_update(prop_meta, value)

            if update_payload:
                properties[prop_name] = update_payload

        if outcome_label:
            for prop_name in ("Win/Loss", "Outcome", "Result"):
                matched_name = self._find_property_name([prop_name])
                if not matched_name:
                    continue

                prop_meta = db_properties[matched_name]
                update_payload = self._build_scalar_property_update(prop_meta, outcome_label.title())
                if update_payload:
                    properties[matched_name] = update_payload
                    break

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            response = requests.post(
                f"{self.base_url}/pages",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            response_data = response.json()
            response_data["notion_url"] = response_data.get("url")
            response_data["created_at"] = response_data.get("created_time")
            response_data["rr_value"] = rr_value
            response_data["outcome"] = outcome_label
            print("Trade row created successfully in Notion")
            return response_data
        except requests.exceptions.HTTPError as exc:
            try:
                error_detail = exc.response.json()
                print(f"Notion API Error: {error_detail.get('message', str(exc))}")
            except Exception:
                print(f"Failed to add trade to Notion: {exc}")
            raise
        except requests.exceptions.RequestException as exc:
            print(f"Failed to add trade to Notion: {exc}")
            raise

    def update_trade(self, page_id: str, updates: dict[str, Any]) -> dict[str, Any]:
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

        response = requests.patch(
            f"{self.base_url}/pages/{page_id}",
            headers=self.headers,
            json={"properties": properties},
            timeout=15,
        )
        response.raise_for_status()
        print("Trade row updated in Notion")
        return response.json()


def load_notion_credentials() -> tuple[str, str]:
    api_token = os.getenv("NOTION_API_TOKEN")
    database_id = os.getenv("NOTION_TRADES_DATABASE_ID")
    if not api_token or not database_id:
        raise ValueError(
            "Please set NOTION_API_TOKEN and NOTION_TRADES_DATABASE_ID environment variables."
        )
    return api_token, database_id
