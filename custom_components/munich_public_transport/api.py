import aiohttp
import asyncio
from datetime import datetime
from typing import List, Dict, Any
import logging

_LOGGER = logging.getLogger(__name__)

class MunichTransportAPIError(Exception):
    """Base exception for MunichTransportAPI errors."""

class NetworkError(MunichTransportAPIError):
    """Raised when there's a network-related error."""

class APIError(MunichTransportAPIError):
    """Raised when the API returns an error or unexpected response."""


class MunichTransportAPI:
    BASE_URL = "https://www.mvg.de/api/bgw-pt/v3"

    @staticmethod
    async def _make_request(url: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        _LOGGER.error(f"API request failed with status {response.status}: {url}")
                        raise APIError(f"API request failed with status {response.status}")
                    return await response.json()
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Network error occurred: {e}")
            raise NetworkError(f"Network error: {e}") from e
        except ValueError as e:
            _LOGGER.error(f"Failed to parse API response: {e}")
            raise APIError(f"Failed to parse API response: {e}") from e

    @staticmethod
    async def fetch_stations(query: str) -> List[Dict[str, Any]]:
        """Fetch stations based on a search query."""
        try:
            data = await MunichTransportAPI._make_request(f"{MunichTransportAPI.BASE_URL}/locations", params={"query": query})
            stations = [
                {
                    "id": station["globalId"],
                    "name": station["name"],
                    "place": station.get("place", ""),
                    "products": station.get("transportTypes", []),
                }
                for station in data if station["type"] == "STATION"
            ]
            if not stations:
                _LOGGER.warning(f"No stations found for query: {query}")
            return stations
        except MunichTransportAPIError as e:
            _LOGGER.error(f"Error fetching stations: {e}")
            raise

    @staticmethod
    async def fetch_departures(station_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch departures for a given station ID."""
        try:
            data = await MunichTransportAPI._make_request(f"{MunichTransportAPI.BASE_URL}/departures", params={"globalId": station_id, "limit": limit})
            departures = [
                {
                    "line": dep["label"],
                    "destination": dep["destination"],
                    "realtime_departure": dep.get("realtimeDepartureTime", None) / 1000,
                    "planned_departure": dep.get("plannedDepartureTime", None) / 1000,
                    "type": dep["transportType"],
                    "cancelled": dep.get("cancelled", False),
                    "messages": [msg for msg in dep.get("messages", [])],
                    "platform": dep.get("platform", ""),
                    "delay": dep.get("delayInMinutes", 0),
                    "icon": MunichTransportAPI.get_icon(dep["transportType"]),
                    "occupancy": dep.get("occupancy", "UNKNOWN"),
                    "network": dep.get("network", ""),
                }
                for dep in data
            ]
            _LOGGER.debug(f"Departures: {departures}")
            if not departures:
                _LOGGER.warning(f"No departures found for station ID: {station_id}")
            return departures
        except MunichTransportAPIError as e:
            _LOGGER.error(f"Error fetching departures: {e}")
            raise

    @staticmethod
    async def fetch_lines(station_id: str) -> List[Dict[str, Any]]:
        """Fetch lines for a given station ID."""
        try:
            data = await MunichTransportAPI._make_request(f"{MunichTransportAPI.BASE_URL}/lines/{station_id}")
            lines = [
                {
                    "label": line["label"],
                    "type": line["transportType"],
                    "network": line["network"],
                }
                for line in data
            ]
            if not lines:
                _LOGGER.warning(f"No lines found for station ID: {station_id}")
            return lines
        except MunichTransportAPIError as e:
            _LOGGER.error(f"Error fetching lines: {e}")
            raise

    @staticmethod
    def get_icon(transport_type: str) -> str:
        """Return the appropriate icon for the transport type."""
        icons = {
            "UBAHN": "mdi:subway-variant",
            "TRAM": "mdi:tram",
            "SBAHN": "mdi:train",
            "BUS": "mdi:bus",
            "REGIONAL_BUS": "mdi:bus-clock",
            "RUFTAXI": "mdi:taxi",
        }
        return icons.get(transport_type, "mdi:train-car")

    @staticmethod
    async def fetch_messages() -> List[Dict[str, Any]]:
        """Fetch messages from the API."""
        try:
            data = await MunichTransportAPI._make_request(f"{MunichTransportAPI.BASE_URL}/messages")
            messages = [
                {
                    "title": msg["title"],
                    "description": msg["description"],
                    "type": msg["type"],
                    "valid_from": datetime.fromtimestamp(msg.get("validFrom", 0) / 1000).isoformat() if msg.get("validFrom") else None,
                    "valid_to": datetime.fromtimestamp(msg.get("validTo", 0) / 1000).isoformat() if msg.get("validTo") else None,
                    "lines": [line["label"] for line in msg.get("lines", [])],
                }
                for msg in data
            ]
            if not messages:
                _LOGGER.warning("No messages found")
            return messages
        except MunichTransportAPIError as e:
            _LOGGER.error(f"Error fetching messages: {e}")
            raise

    @staticmethod
    def calculate_minutes_until(timestamp: int) -> int:
        """Calculate minutes until the given timestamp."""
        departure_time = datetime.fromtimestamp(timestamp)  # Convert milliseconds to seconds
        now = datetime.now()
        time_diff = departure_time - now
        return max(0, int(time_diff.total_seconds() / 60))