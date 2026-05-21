# Munich Public Transport

Home Assistant custom integration for Munich public transport departures.

This project is not affiliated with, endorsed by, or sponsored by MVG, MVV, or
Stadtwerke München.

## Status

This branch is a rewrite. The legacy integration code has been removed and the
new integration is intentionally built as a thin Home Assistant adapter around
the standalone `munich-transport` Python package.

## Architecture

The integration avoids one API request per sensor. Each configured station owns
one departure coordinator:

```text
station config entry
  one DataUpdateCoordinator
    one MVG departures request per refresh

line/direction sensors
  no direct MVG requests
  filter coordinator data locally
```

Line and direction options are discovered from the station schedule catalog.
Temporary termini and night lines are represented as stable direction options
when MVG publishes them in the catalog.

## Current Features

- UI config flow
- station search
- station selection
- line/direction selection
- one timestamp sensor per selected line/direction pairing
- shared station departure polling
- transient MVG error handling with `Retry-After` support when Home Assistant
  supports it

## Dependency

```json
"requirements": ["munich-transport==0.1.0"]
```

Home Assistant installs the standalone client from PyPI.

## Setup

1. Add the integration from the Home Assistant UI.
2. Search for a station.
3. Select the resolved station.
4. Select the line and direction pairings to expose as sensors.

Each configured station becomes one device. Each selected line/direction pairing
becomes one timestamp sensor whose state is the next realtime departure.

## Notes

- S-Bahn departures may appear in live departures even when MVG does not expose
  matching entries in the station schedule catalog.
- If MVG temporarily returns `429`, `502`, `503`, or `504`, the coordinator
  marks the update as failed and retries centrally instead of letting each
  entity retry independently.
- The integration does not use the old custom integration's API layer.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
