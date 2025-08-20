from urllib.parse import urlencode

import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging
import time

_LOGGER = logging.getLogger(__name__)

class MunichTransportAPIError(Exception):
    """Base exception for MunichTransportAPI errors."""

class NetworkError(MunichTransportAPIError):
    """Raised when there's a network-related error."""

class APIError(MunichTransportAPIError):
    """Raised when the API returns an error or unexpected response."""

class RateLimitError(MunichTransportAPIError):
    """Raised when the API rate limit is exceeded."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class MunichTransportAPI:
    BASE_URL = "https://www.mvg.de/api/bgw-pt/v3"
    
    # Simple in-memory cache for rate limiting scenarios
    _cache: Dict[str, Dict[str, Any]] = {}
    _cache_timestamps: Dict[str, float] = {}

    @staticmethod
    def _get_cache_key(url: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Generate a cache key for the request."""
        if params:
            sorted_params = sorted(params.items())
            param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
            return f"{url}?{param_str}"
        return url

    @staticmethod
    def _get_cached_response(cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if available and not expired."""
        try:
            from .const import RATE_LIMIT_CACHE_DURATION
        except ImportError:
            # Fallback for direct imports or testing
            RATE_LIMIT_CACHE_DURATION = 900
        
        if cache_key not in MunichTransportAPI._cache:
            return None
            
        timestamp = MunichTransportAPI._cache_timestamps.get(cache_key, 0)
        if time.time() - timestamp > RATE_LIMIT_CACHE_DURATION:
            # Cache expired, remove it
            MunichTransportAPI._cache.pop(cache_key, None)
            MunichTransportAPI._cache_timestamps.pop(cache_key, None)
            return None
            
        return MunichTransportAPI._cache[cache_key]

    @staticmethod
    def _cache_response(cache_key: str, response: Dict[str, Any]) -> None:
        """Cache a successful response."""
        MunichTransportAPI._cache[cache_key] = response
        MunichTransportAPI._cache_timestamps[cache_key] = time.time()

    @staticmethod
    async def _make_request_with_retry(url: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request with retry logic for rate limiting."""
        try:
            from .const import MAX_RETRIES, BASE_RETRY_DELAY, MAX_RETRY_DELAY
        except ImportError:
            # Fallback for direct imports or testing
            MAX_RETRIES = 3
            BASE_RETRY_DELAY = 2
            MAX_RETRY_DELAY = 300
        
        cache_key = MunichTransportAPI._get_cache_key(url, params)
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await MunichTransportAPI._make_request(url, params)
            except RateLimitError as e:
                _LOGGER.warning(f"Rate limit hit on attempt {attempt + 1}/{MAX_RETRIES + 1}: {e}")
                
                # Try to return cached data if available
                cached_response = MunichTransportAPI._get_cached_response(cache_key)
                if cached_response is not None:
                    _LOGGER.info(f"Returning cached data for {url} due to rate limiting")
                    return cached_response
                
                # If this is the last attempt, raise the error
                if attempt == MAX_RETRIES:
                    _LOGGER.error(f"Max retries exceeded for {url}, no cached data available")
                    raise
                
                # Calculate delay with exponential backoff
                if e.retry_after:
                    delay = min(e.retry_after, MAX_RETRY_DELAY)
                    _LOGGER.info(f"API provided retry-after: {e.retry_after}s, using {delay}s")
                else:
                    delay = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    _LOGGER.info(f"Using exponential backoff: {delay}s")
                
                _LOGGER.info(f"Waiting {delay} seconds before retry {attempt + 2}")
                await asyncio.sleep(delay)
        
        # This should never be reached due to the raise in the loop
        raise RateLimitError("Max retries exceeded")

    @staticmethod
    async def _make_request(url: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the API."""
        cache_key = MunichTransportAPI._get_cache_key(url, params)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    # Handle rate limiting
                    if response.status == 429:
                        retry_after = None
                        if 'retry-after' in response.headers:
                            try:
                                retry_after = int(response.headers['retry-after'])
                            except ValueError:
                                _LOGGER.warning(f"Invalid retry-after header: {response.headers['retry-after']}")
                        
                        error_msg = f"Rate limit exceeded (HTTP 429)"
                        if retry_after:
                            error_msg += f", retry after {retry_after} seconds"
                        
                        raise RateLimitError(error_msg, retry_after)
                    
                    # Handle service unavailable (sometimes used for rate limiting)
                    if response.status == 503:
                        retry_after = None
                        if 'retry-after' in response.headers:
                            try:
                                retry_after = int(response.headers['retry-after'])
                            except ValueError:
                                pass
                        
                        # Check if this might be rate limiting vs actual service unavailable
                        response_text = await response.text()
                        if any(keyword in response_text.lower() for keyword in ['rate', 'limit', 'quota', 'throttle']):
                            error_msg = f"Service rate limited (HTTP 503)"
                            if retry_after:
                                error_msg += f", retry after {retry_after} seconds"
                            raise RateLimitError(error_msg, retry_after)
                    
                    if response.status != 200:
                        _LOGGER.error(f"API request failed with status {response.status}: {url}")
                        raise APIError(f"API request failed with status {response.status}")
                    
                    data = await response.json()
                    
                    # Cache successful responses
                    MunichTransportAPI._cache_response(cache_key, data)
                    
                    return data
                    
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
            data = await MunichTransportAPI._make_request_with_retry(f"{MunichTransportAPI.BASE_URL}/locations", params={"query": query})
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
    async def fetch_departures(station_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch departures for a given station ID."""
        try:
            data = await MunichTransportAPI._make_request_with_retry(f"{MunichTransportAPI.BASE_URL}/departures", params={"globalId": station_id, "limit": limit})
            departures = [
                {
                    "line": dep["label"],
                    "destination": dep["destination"],
                    "realtime_departure": dep.get("realtimeDepartureTime", None) / 1000,
                    "planned_departure": dep.get("plannedDepartureTime", None) / 1000,
                    "type": dep["transportType"],
                    "cancelled": dep.get("cancelled", False),
                    "messages": [msg for msg in dep.get("messages", [])],
                    "platform": dep.get("platform", None),
                    "platform_changed": dep.get("platformChanged", False),
                    "stop_position_number": dep.get("stopPositionNumber", None),
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
            data = await MunichTransportAPI._make_request_with_retry(f"{MunichTransportAPI.BASE_URL}/lines/{station_id}")
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
            data = await MunichTransportAPI._make_request_with_retry(f"{MunichTransportAPI.BASE_URL}/messages")
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