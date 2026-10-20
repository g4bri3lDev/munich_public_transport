"""Test the Munich Public Transport config and subentry flows."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from munich_transport.exceptions import MunichTransportError, ParseError
from munich_transport.models import Location, Station, StationDirectionOption
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.munich_public_transport.const import (
    CONF_DIRECTION_OPTION_IDS,
    DOMAIN,
    SUBENTRY_TYPE_STATION,
)

from . import STATION, STATION_DATA, SUBENTRY_ID

BONNER_PLATZ = Station(
    global_id="de:09162:410",
    name="Bonner Platz",
    place="München",
    latitude=48.1665,
    longitude=11.5786,
    abbreviation="BP",
)
SUBWAY_SECTION = {"subway": {"direction_option_ids_subway": ["SUBWAY:U6:H"]}}

type Configure = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _location(station: Station) -> Location:
    return Location(
        name=station.name,
        place=station.place,
        latitude=station.latitude,
        longitude=station.longitude,
        kind="STATION",
        global_id=station.global_id,
    )


@pytest.fixture
def locations() -> list[Location]:
    """Return the station search results; parametrize to override."""
    return [_location(STATION)]


@pytest.fixture(autouse=True)
def mock_search(mock_client: MagicMock, locations: list[Location]) -> None:
    """Answer station searches with the locations fixture."""
    mock_client.search_locations.return_value = locations


@pytest.fixture
async def user_flow(hass: HomeAssistant) -> str:
    """Start the integration's config flow and return its id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return result["flow_id"]


@pytest.fixture
async def station_flow(hass: HomeAssistant, init_integration: MockConfigEntry) -> str:
    """Start an "Add station" subentry flow and return its id."""
    result = await hass.config_entries.subentries.async_init(
        (init_integration.entry_id, SUBENTRY_TYPE_STATION),
        context={"source": SOURCE_USER},
    )
    assert result["step_id"] == "user"
    return result["flow_id"]


async def _search_and_select(
    configure: Configure, flow_id: str, station: Station = STATION
) -> dict[str, Any]:
    result = await configure(flow_id, {"query": f"  {station.name}  "})
    assert result["step_id"] == "select_station"
    return await configure(flow_id, {"selected_station": station.global_id})


async def test_user_flow_creates_entry_with_first_station(
    hass: HomeAssistant, mock_client: MagicMock, user_flow: str
) -> None:
    """Test adding the integration creates the MVG entry and its first station."""
    configure = hass.config_entries.flow.async_configure

    result = await _search_and_select(configure, user_flow)
    assert result["step_id"] == "select_directions"
    mock_client.search_locations.assert_awaited_once_with("Münchner Freiheit")

    result = await configure(user_flow, SUBWAY_SECTION)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MVG"
    assert result["data"] == {}
    [subentry] = result["result"].subentries.values()
    assert subentry.subentry_type == SUBENTRY_TYPE_STATION
    assert subentry.title == STATION.name
    assert subentry.unique_id == STATION.global_id
    assert dict(subentry.data) == {
        **STATION_DATA,
        CONF_DIRECTION_OPTION_IDS: ["SUBWAY:U6:H"],
    }


async def test_user_flow_single_instance(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a second MVG entry is not allowed."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.parametrize(
    ("side_effect", "locations", "error"),
    [
        (MunichTransportError("boom"), [], "cannot_connect"),
        (None, [], "no_stations_found"),
        (
            None,
            [
                Location(
                    name="Somewhere",
                    place=None,
                    latitude=0,
                    longitude=0,
                    kind="ADDRESS",
                )
            ],
            "no_stations_found",
        ),
    ],
)
async def test_search_errors_recover(
    hass: HomeAssistant,
    mock_client: MagicMock,
    user_flow: str,
    side_effect: Exception | None,
    error: str,
) -> None:
    """Test search errors are shown and the flow recovers on retry."""
    configure = hass.config_entries.flow.async_configure
    mock_client.search_locations.side_effect = side_effect

    result = await configure(user_flow, {"query": "x"})
    assert result["errors"] == {"base": error}

    mock_client.search_locations.side_effect = None
    mock_client.search_locations.return_value = [_location(STATION)]
    result = await configure(user_flow, {"query": "x"})
    assert result["step_id"] == "select_station"


@pytest.mark.parametrize(
    ("attribute", "side_effect", "return_value", "error"),
    [
        ("station", ParseError("bad"), None, "invalid_station"),
        ("station", MunichTransportError("boom"), None, "cannot_connect"),
        (
            "direction_options_for_station",
            MunichTransportError("boom"),
            None,
            "cannot_connect",
        ),
        ("direction_options_for_station", None, [], "no_direction_options"),
    ],
)
async def test_select_station_errors_recover(
    hass: HomeAssistant,
    mock_client: MagicMock,
    user_flow: str,
    attribute: str,
    side_effect: Exception | None,
    return_value: list | None,
    error: str,
) -> None:
    """Test station lookup errors are shown and the flow recovers on retry."""
    configure = hass.config_entries.flow.async_configure
    mock = getattr(mock_client, attribute)
    original = mock.return_value
    mock.side_effect = side_effect
    if return_value is not None:
        mock.return_value = return_value

    result = await _search_and_select(configure, user_flow)
    assert result["step_id"] == "select_station"
    assert result["errors"] == {"base": error}

    mock.side_effect = None
    mock.return_value = original
    result = await configure(user_flow, {"selected_station": STATION.global_id})
    assert result["step_id"] == "select_directions"


@pytest.mark.parametrize(
    "direction_options",
    [
        [
            StationDirectionOption(
                id="UBAHN:U6:H",
                schedule_kind="UBAHN",
                line_label="U6",
                direction_key="H",
                directions=("Klinikum Großhadern",),
                raw_directions=("Klinikum Großhadern",),
                schedule_codes=(),
            )
        ]
    ],
)
async def test_departure_derived_options_use_transport_sections(
    hass: HomeAssistant, user_flow: str
) -> None:
    """Test U-Bahn options built from live departures land in the U-Bahn section."""
    result = await _search_and_select(
        hass.config_entries.flow.async_configure, user_flow
    )

    assert [str(key) for key in result["data_schema"].schema] == ["subway"]


@pytest.mark.parametrize("locations", [[_location(BONNER_PLATZ), _location(STATION)]])
async def test_add_station(
    hass: HomeAssistant,
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
    station_flow: str,
) -> None:
    """Test adding a second station as a subentry."""
    configure = hass.config_entries.subentries.async_configure
    mock_client.station.return_value = BONNER_PLATZ

    await _search_and_select(configure, station_flow, BONNER_PLATZ)
    result = await configure(station_flow, SUBWAY_SECTION)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {
        subentry.unique_id for subentry in init_integration.subentries.values()
    } == {
        STATION.global_id,
        BONNER_PLATZ.global_id,
    }
    # The entry reloads, so the new station is set up right away.
    assert len(init_integration.runtime_data.stations) == 2


async def test_add_station_already_configured(
    hass: HomeAssistant, mock_client: MagicMock, station_flow: str
) -> None:
    """Test a configured station aborts before any lookups."""
    mock_client.station.reset_mock()

    result = await _search_and_select(
        hass.config_entries.subentries.async_configure, station_flow
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_client.station.assert_not_awaited()


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_STATION),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": SUBENTRY_ID},
    )


async def test_reconfigure_station(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test changing a station's directions preselects the current ones."""
    result = await _start_reconfigure(hass, init_integration)
    assert result["step_id"] == "reconfigure"
    defaults = {
        str(key): key.default()
        for key in result["data_schema"].schema["subway"].schema.schema
    }
    assert defaults == {"direction_option_ids_subway": ["SUBWAY:U6:H", "SUBWAY:U6:R"]}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SUBWAY_SECTION
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.subentries[SUBENTRY_ID].data[CONF_DIRECTION_OPTION_IDS] == [
        "SUBWAY:U6:H"
    ]
    [station] = init_integration.runtime_data.stations.values()
    assert [direction.id for direction in station.directions] == ["SUBWAY:U6:H"]


async def test_reconfigure_station_cannot_connect(
    hass: HomeAssistant, mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test a failed lookup aborts instead of offering an empty form.

    Submitting an empty form would save an empty selection and remove every
    direction of the station.
    """
    mock_client.direction_options_for_station.side_effect = MunichTransportError("boom")

    result = await _start_reconfigure(hass, init_integration)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert init_integration.subentries[SUBENTRY_ID].data == STATION_DATA


async def test_reconfigure_removes_deselected_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Test dropping a direction removes its entities instead of orphaning them."""
    result = await _start_reconfigure(hass, init_integration)
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], SUBWAY_SECTION
    )
    await hass.async_block_till_done()

    unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, init_integration.entry_id
        )
    }
    assert not {uid for uid in unique_ids if "SUBWAY:U6:R" in uid}
    # One per station, two for the remaining direction, one for U6.
    assert len(unique_ids) == 1 + 2 + 1
