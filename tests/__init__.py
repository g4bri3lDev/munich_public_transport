"""Tests for the Munich Public Transport integration."""

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util
from munich_transport.models import Departure, Line, Station, StationDirectionOption

STATION = Station(
    global_id="de:09162:500",
    name="Münchner Freiheit",
    place="München",
    latitude=48.161962,
    longitude=11.586497,
    diva_id=500,
    abbreviation="MU",
)

ENTRY_DATA = {
    "name": STATION.name,
    "station_global_id": STATION.global_id,
    "station_abbreviation": STATION.abbreviation,
    "station_place": STATION.place,
}

U6 = Line(label="U6", transport_type="UBAHN", network="swm")

DIRECTION_OPTIONS = [
    StationDirectionOption(
        id="SUBWAY:U6:H",
        schedule_kind="SUBWAY",
        line_label="U6",
        direction_key="H",
        directions=("Klinikum Großhadern", "Goetheplatz / Klinikum Großhadern"),
        raw_directions=(
            "Klinikum Großhadern, gültig ab 14.12.2025",
            "Goetheplatz / Klinikum Großhadern (gültig vom 05.10.-27.11.2026)",
        ),
        schedule_codes=("H", "I"),
    ),
    StationDirectionOption(
        id="SUBWAY:U6:R",
        schedule_kind="SUBWAY",
        line_label="U6",
        direction_key="R",
        directions=(
            "Garching, Forschungszentrum",
            "Implerstraße / Garching-Forschungszentrum",
        ),
        raw_directions=(
            "Garching, Forschungszentrum, gültig ab 14.12.2025",
            "Implerstraße / Garching-Forschungszentrum (gültig vom 05.10.-27.11.2026)",
        ),
        schedule_codes=("R", "S"),
    ),
]


def make_departure(
    minutes: int,
    *,
    line: Line = U6,
    destination: str = "Klinikum Großhadern",
    direction_key: str = "H",
    delay: int = 0,
    now: datetime | None = None,
) -> Departure:
    """Build a departure `minutes` from now."""
    planned = (now or dt_util.utcnow()) + timedelta(minutes=minutes)
    return Departure(
        planned_departure=planned,
        realtime_departure=planned + timedelta(minutes=delay),
        line=line,
        destination=destination,
        realtime=True,
        cancelled=False,
        station_global_id=STATION.global_id,
        direction_key=direction_key,
        platform=1,
        delay_minutes=delay,
    )
