"""Test the Munich Public Transport sensors and binary sensors."""

from collections.abc import Generator
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import Disruption, Line
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.munich_public_transport.const import (
    DEFAULT_MESSAGES_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)

from . import NOW, STATION, U6, make_departure

U3 = Line(label="U3", transport_type="UBAHN", network="swm")
HOUR = timedelta(hours=1)

DEPARTURE = "sensor.munchner_freiheit_u6_klinikum_grosshadern"
DISRUPTIONS = "sensor.munchner_freiheit_disruptions"
U6_DISRUPTION = "binary_sensor.munchner_freiheit_u6_disruption"


def _disruption(
    title: str,
    *,
    lines: tuple[Line, ...] = (),
    stations: tuple[str, ...] = (),
    valid_to: datetime | None = None,
) -> Disruption:
    return Disruption(
        title=title,
        description_html=f"<p>{title}</p>",
        kind="INCIDENT",
        valid_to=valid_to,
        lines=lines,
        station_global_ids=stations,
    )


@pytest.fixture
def platform() -> Platform:
    """Return the platform to snapshot; parametrize to choose."""
    return Platform.SENSOR


@pytest.fixture
def single_platform(platform: Platform) -> Generator[None]:
    """Load only one platform, as snapshot_platform requires."""
    with patch("custom_components.munich_public_transport.PLATFORMS", [platform]):
        yield


@pytest.fixture
def catalog_unreachable(mock_client: MagicMock) -> None:
    """Make the direction catalog lookup fail."""
    mock_client.direction_options_for_station.side_effect = MunichTransportError("boom")


@pytest.fixture
def messages_unreachable(mock_client: MagicMock) -> None:
    """Make the service message request fail."""
    mock_client.messages.side_effect = MunichTransportError("boom")


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "single_platform")
@pytest.mark.parametrize("platform", [Platform.SENSOR, Platform.BINARY_SENSOR])
@pytest.mark.parametrize(
    "departures",
    [
        [
            make_departure(
                8, destination="Garching, Forschungszentrum", direction_key="R", now=NOW
            ),
            make_departure(3, delay=2, now=NOW),
            make_departure(13, now=NOW),
            # Not selected, so it must not show up in any sensor.
            make_departure(
                1, line=U3, destination="Moosach Bf", direction_key="R", now=NOW
            ),
        ]
    ],
)
@pytest.mark.parametrize("messages", [[_disruption("U6 works", lines=(U6,))]])
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    init_integration: MockConfigEntry,
) -> None:
    """Test every entity, including the ones disabled by default."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_disabled_by_default(
    entity_registry: er.EntityRegistry, init_integration: MockConfigEntry
) -> None:
    """Test the following departure sensor starts disabled."""
    entity = entity_registry.async_get(f"{DEPARTURE}_following_departure")
    assert entity is not None
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.parametrize(
    "departures", [[make_departure(4, destination="Goetheplatz", now=NOW)]]
)
async def test_short_turn_keeps_entity_id(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a short-turn changes neither the entity id nor the name."""
    state = hass.states.get(DEPARTURE)
    assert state.name == "Münchner Freiheit U6 → Klinikum Großhadern"
    assert state.state == (NOW + timedelta(minutes=4)).isoformat()


@pytest.mark.parametrize(
    "departures",
    [[replace(make_departure(2, now=NOW), cancelled=True), make_departure(6, now=NOW)]],
)
async def test_cancelled_departures_are_skipped(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test cancelled departures do not count as the next departure."""
    assert hass.states.get(DEPARTURE).state == (NOW + timedelta(minutes=6)).isoformat()


@pytest.mark.parametrize("departures", [[]])
async def test_no_departures(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test sensors report unknown when nothing departs."""
    assert hass.states.get(DEPARTURE).state == STATE_UNKNOWN


@pytest.mark.usefixtures("catalog_unreachable")
async def test_names_without_catalog(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test directions still get sensors when the catalog is unreachable."""
    state = hass.states.get("sensor.munchner_freiheit_u6_unknown")
    assert state is not None
    assert state.state == (NOW + timedelta(minutes=3)).isoformat()


async def test_departures_unavailable_and_recover(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
) -> None:
    """Test departure sensors go unavailable on errors and come back."""
    mock_client.departures.side_effect = MunichTransportError("timeout")
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(DEPARTURE).state == STATE_UNAVAILABLE

    mock_client.departures.side_effect = None
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(DEPARTURE).state != STATE_UNAVAILABLE


@pytest.mark.parametrize(
    "messages",
    [
        [
            _disruption("This station", stations=(STATION.global_id,), lines=(U3,)),
            _disruption("Other station", stations=("de:09162:1",), lines=(U6,)),
            _disruption("Selected line", lines=(U6,), valid_to=NOW + HOUR),
            _disruption("Other line", lines=(U3,)),
            _disruption("Network wide"),
            _disruption("Expired", lines=(U6,), valid_to=NOW - HOUR),
        ]
    ],
)
async def test_disruptions(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
) -> None:
    """Test station and line disruptions use the library's relevance rules."""
    assert hass.states.get(DISRUPTIONS).state == "3"
    assert hass.states.get(U6_DISRUPTION).state == STATE_ON

    mock_client.messages.return_value = [_disruption("Network wide")]
    freezer.tick(DEFAULT_MESSAGES_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(DISRUPTIONS).state == "1"
    # Network-wide announcements do not mark every line as disrupted.
    assert hass.states.get(U6_DISRUPTION).state == STATE_OFF


@pytest.mark.usefixtures("messages_unreachable")
async def test_messages_failure_does_not_block_setup(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test service messages are optional for setting up stations."""
    assert hass.states.get(DEPARTURE).state != STATE_UNAVAILABLE
    assert hass.states.get(DISRUPTIONS).state == STATE_UNAVAILABLE
    assert hass.states.get(U6_DISRUPTION).state == STATE_UNAVAILABLE
