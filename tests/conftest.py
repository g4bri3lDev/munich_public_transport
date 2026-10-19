"""Munich Public Transport test fixtures."""

from collections.abc import Generator
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from munich_transport.client import MunichTransportClient
from munich_transport.models import Departure, Disruption, StationDirectionOption
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.munich_public_transport.const import (
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    SUBENTRY_TYPE_STATION,
)

from . import DIRECTION_OPTIONS, NOW, STATION, STATION_DATA, SUBENTRY_ID, make_departure

# Every module that imports the client by name needs its own patch, since
# patching the source module would not reach the already-bound references.
_CLIENT_NAMESPACES = (
    "custom_components.munich_public_transport.MunichTransportClient",
    "custom_components.munich_public_transport.config_flow.MunichTransportClient",
    "custom_components.munich_public_transport.migration.MunichTransportClient",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration in every test."""


# PHCC provides this too, but whether its plugin fixture wins over syrupy's own
# depends on plugin load order: without it snapshots resolve to __snapshots__/
# instead of snapshots/. Home Assistant core defines it for the same reason.
@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use the Home Assistant snapshot extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable entities that are disabled by default, as core's fixture does."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture(autouse=True)
def now(freezer: FrozenDateTimeFactory) -> datetime:
    """Freeze the clock, so departure times and states are deterministic.

    Autouse, so tests that parametrize departures still run at NOW.
    """
    freezer.move_to(NOW)
    return NOW


@pytest.fixture
def departures() -> list[Departure]:
    """Return the live departures MVG reports; parametrize to override."""
    return [
        make_departure(3, now=NOW),
        make_departure(
            8, destination="Garching, Forschungszentrum", direction_key="R", now=NOW
        ),
    ]


@pytest.fixture
def messages() -> list[Disruption]:
    """Return the service messages MVG reports; parametrize to override."""
    return []


@pytest.fixture
def direction_options() -> list[StationDirectionOption]:
    """Return the station's selectable directions; parametrize to override."""
    return DIRECTION_OPTIONS


@pytest.fixture
def mock_client(
    departures: list[Departure],
    messages: list[Disruption],
    direction_options: list[StationDirectionOption],
) -> Generator[MagicMock]:
    """Patch the MVG client with the departure, message and option fixtures."""
    # A spec turns every async client method into an AsyncMock and makes a
    # misspelled method fail instead of silently returning a MagicMock.
    client = MagicMock(spec=MunichTransportClient)
    client.search_locations.return_value = []
    client.station.return_value = STATION
    client.direction_options_for_station.return_value = direction_options
    client.departures.return_value = departures
    client.messages.return_value = messages
    with ExitStack() as stack:
        for target in _CLIENT_NAMESPACES:
            stack.enter_context(patch(target, return_value=client))
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return an MVG entry with Münchner Freiheit and both U6 directions."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="MVG",
        version=CONFIG_ENTRY_VERSION,
        data={},
        subentries_data=[
            ConfigSubentryData(
                data=STATION_DATA,
                subentry_id=SUBENTRY_ID,
                subentry_type=SUBENTRY_TYPE_STATION,
                title=STATION.name,
                unique_id=STATION.global_id,
            )
        ],
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the MVG entry and return it."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def station_device(
    device_registry: dr.DeviceRegistry, init_integration: MockConfigEntry
) -> dr.DeviceEntry:
    """Return the station device of the set-up entry."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, STATION.global_id), init_integration.entry_id
    )
    assert device is not None
    return device
