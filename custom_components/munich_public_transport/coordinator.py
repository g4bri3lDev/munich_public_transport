"""Data coordinators for the Munich Public Transport integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import ApiError, MunichTransportError
from munich_transport.models import Departure, Disruption

from .const import DEFAULT_MESSAGES_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TRANSIENT_RETRY_AFTER = 60.0
_MAX_RETRY_AFTER = 15 * 60.0


class MunichTransportDepartureCoordinator(DataUpdateCoordinator[list[Departure]]):
    """Fetch live departures once for a configured station."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: MunichTransportClient,
        station_global_id: str,
        station_name: str,
    ) -> None:
        """Initialize the station departure coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{station_name}",
            config_entry=config_entry,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self._client = client
        self._station_global_id = station_global_id

    async def _async_update_data(self) -> list[Departure]:
        """Fetch live station departures."""

        try:
            return await self._client.departures(self._station_global_id)
        except ApiError as err:
            if err.transient:
                raise _transient_update_failed(err) from err
            raise UpdateFailed(f"MVG returned HTTP {err.status}") from err
        except MunichTransportError as err:
            raise UpdateFailed(f"Error communicating with MVG: {err}") from err


class MunichTransportMessagesCoordinator(DataUpdateCoordinator[list[Disruption]]):
    """Fetch MVG service messages once for the integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MunichTransportClient,
    ) -> None:
        """Initialize the messages coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-messages",
            update_interval=DEFAULT_MESSAGES_SCAN_INTERVAL,
            always_update=False,
        )
        self._client = client

    async def _async_update_data(self) -> list[Disruption]:
        """Fetch MVG service messages."""

        try:
            return await self._client.messages()
        except ApiError as err:
            if err.transient:
                raise _transient_update_failed(err) from err
            raise UpdateFailed(f"MVG returned HTTP {err.status}") from err
        except MunichTransportError as err:
            raise UpdateFailed(f"Error communicating with MVG: {err}") from err


def _transient_update_failed(err: ApiError) -> UpdateFailed:
    retry_after = _sanitize_retry_after(err.retry_after)
    message = f"MVG is temporarily unavailable: HTTP {err.status}"

    try:
        return UpdateFailed(message, retry_after=retry_after)
    except TypeError:
        return UpdateFailed(message)


def _sanitize_retry_after(value: float | None) -> float:
    if value is None:
        return _DEFAULT_TRANSIENT_RETRY_AFTER
    return min(max(value, 1.0), _MAX_RETRY_AFTER)
