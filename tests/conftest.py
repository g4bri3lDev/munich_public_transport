"""Munich Public Transport test fixtures."""

from collections.abc import Generator
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from munich_transport.client import MunichTransportClient
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.munich_public_transport.const import (
    CONF_DIRECTION_OPTION_IDS,
    DOMAIN,
)

from . import DIRECTION_OPTIONS, ENTRY_DATA, STATION, make_departure

# Every module that imports the client by name needs its own patch, since
# patching the source module would not reach the already-bound references.
_CLIENT_NAMESPACES = (
    "custom_components.munich_public_transport.MunichTransportClient",
    "custom_components.munich_public_transport.config_flow.MunichTransportClient",
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
def mock_client() -> Generator[MagicMock]:
    """Patch the MVG client with canned Münchner Freiheit responses."""
    # A spec turns every async client method into an AsyncMock and makes a
    # misspelled method fail instead of silently returning a MagicMock.
    client = MagicMock(spec=MunichTransportClient)
    client.search_locations.return_value = []
    client.station.return_value = STATION
    client.station_direction_options_by_abbreviation.return_value = DIRECTION_OPTIONS
    client.departures.return_value = [
        make_departure(3),
        make_departure(8, destination="Garching, Forschungszentrum", direction_key="R"),
    ]
    client.messages.return_value = []
    with ExitStack() as stack:
        for target in _CLIENT_NAMESPACES:
            stack.enter_context(patch(target, return_value=client))
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a migrated (v2) Münchner Freiheit entry with both U6 directions."""
    return MockConfigEntry(
        domain=DOMAIN,
        # Unique ids embed the entry id, so snapshots need a fixed one.
        entry_id="01JMUNCHNERFREIHEIT0000000",
        version=2,
        title=STATION.name,
        unique_id=STATION.global_id,
        data=ENTRY_DATA,
        options={CONF_DIRECTION_OPTION_IDS: [o.id for o in DIRECTION_OPTIONS]},
    )
