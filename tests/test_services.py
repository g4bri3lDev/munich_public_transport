"""Test the Munich Public Transport actions."""

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import Disruption, Line
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.munich_public_transport.const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_GET_DEPARTURES,
)

from . import NOW, U6, make_departure

U3 = Line(label="U3", transport_type="UBAHN", network="swm")


async def _get_departures(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        {"device_id": device_id},
        blocking=True,
        return_response=True,
    )


@pytest.mark.parametrize(
    "departures",
    [
        [
            make_departure(
                8, destination="Garching, Forschungszentrum", direction_key="R", now=NOW
            ),
            replace(make_departure(3, delay=2, now=NOW), cancelled=True),
            make_departure(
                1, line=U3, destination="Moosach Bf", direction_key="R", now=NOW
            ),
        ]
    ],
)
@pytest.mark.parametrize(
    "messages",
    [
        [
            Disruption(
                title="U6 works",
                description_html="<p>U6</p>",
                kind="INCIDENT",
                lines=(U6,),
            ),
            Disruption(
                title="U3 works",
                description_html="<p>U3</p>",
                kind="INCIDENT",
                lines=(U3,),
            ),
        ]
    ],
)
async def test_get_departures(
    hass: HomeAssistant,
    mock_client: MagicMock,
    station_device: dr.DeviceEntry,
) -> None:
    """Test the response has every selected departure and relevant message."""
    mock_client.departures.reset_mock()

    response = await _get_departures(hass, station_device.id)

    # Answered from the cache, so it never adds an MVG request.
    mock_client.departures.assert_not_awaited()
    assert response == {
        "station": {"name": "Münchner Freiheit", "global_id": "de:09162:500"},
        "departures": [
            {
                "line": "U6",
                "transport_type": "UBAHN",
                "network": "swm",
                "destination": "Klinikum Großhadern",
                "direction": "SUBWAY:U6:H",
                "direction_key": "H",
                "planned_departure": "2026-10-19T12:03:00+00:00",
                "realtime_departure": "2026-10-19T12:05:00+00:00",
                "minutes_until_departure": 5,
                "delay": 2,
                "cancelled": True,
                "realtime": True,
                "platform": 1,
                "platform_changed": None,
                "occupancy": None,
            },
            {
                "line": "U6",
                "transport_type": "UBAHN",
                "network": "swm",
                "destination": "Garching, Forschungszentrum",
                "direction": "SUBWAY:U6:R",
                "direction_key": "R",
                "planned_departure": "2026-10-19T12:08:00+00:00",
                "realtime_departure": "2026-10-19T12:08:00+00:00",
                "minutes_until_departure": 8,
                "delay": 0,
                "cancelled": False,
                "realtime": True,
                "platform": 1,
                "platform_changed": None,
                "occupancy": None,
            },
        ],
        "messages": [
            {
                "title": "U6 works",
                "description": "<p>U6</p>",
                "type": "INCIDENT",
                "lines": ["U6"],
                "valid_from": None,
                "valid_to": None,
            }
        ],
    }


@pytest.fixture
def other_device(
    device_registry: dr.DeviceRegistry, init_integration: MockConfigEntry
) -> dr.DeviceEntry:
    """Return a device of the entry that is not a station."""
    return device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id, identifiers={("other", "x")}
    )


async def test_get_departures_not_a_station(
    hass: HomeAssistant, other_device: dr.DeviceEntry
) -> None:
    """Test a device that is not a station is rejected."""
    with pytest.raises(ServiceValidationError) as err:
        await _get_departures(hass, other_device.id)
    assert err.value.translation_key == "invalid_device"


async def test_get_departures_unknown_device(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test an unknown device id is rejected."""
    with pytest.raises(ServiceValidationError) as err:
        await _get_departures(hass, "not-a-device")
    assert err.value.translation_key == "invalid_device"


async def test_get_departures_station_not_loaded(
    hass: HomeAssistant, station_device: dr.DeviceEntry
) -> None:
    """Test a station of an unloaded entry is rejected."""
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(ServiceValidationError) as err:
        await _get_departures(hass, station_device.id)
    assert err.value.translation_key == "station_not_loaded"


async def test_get_departures_unavailable(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    station_device: dr.DeviceEntry,
) -> None:
    """Test stale departures are not served after a failed update."""
    mock_client.departures.side_effect = MunichTransportError("boom")
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError) as err:
        await _get_departures(hass, station_device.id)
    assert err.value.translation_key == "station_unavailable"
