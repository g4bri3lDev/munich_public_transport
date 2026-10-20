# Changelog

## [2.0.0](https://github.com/g4bri3lDev/munich_public_transport/compare/1.0.0...2.0.0) (2026-10-20)


### ⚠ BREAKING CHANGES

* Requires Home Assistant 2026.10.0 or newer.
* All stations become subentries of one MVG entry. Existing stations are migrated automatically and keep their device IDs, and entities with a direct successor keep their entity IDs.
* Departure sensors report the next departure as a timestamp and no longer carry departures, delays, destinations, platforms or messages as attributes. Use the `get_departures` action instead.
* The All departures, Next departure, delay, destination and platform sensors are removed. Disruptions are one binary sensor per line.

### Features

* one MVG entry with a subentry per station ([972fd2e](https://github.com/g4bri3lDev/munich_public_transport/commit/972fd2e1b1542428146b6873e52dbe14ee2552d4))
* remove the station next departure sensor ([3f608cf](https://github.com/g4bri3lDev/munich_public_transport/commit/3f608cf182b29382c439fd2d2c593188686e74d3))
* one disruption sensor per line and no delay or destination sensors ([5c2bdb4](https://github.com/g4bri3lDev/munich_public_transport/commit/5c2bdb4d60ab03222aec608863c7daf3bd1cc7f0))
* remove the platform sensor ([426eda9](https://github.com/g4bri3lDev/munich_public_transport/commit/426eda9f692c746f2415be57ca8ffb6bf8bf4888))


### Bug Fixes

* remove entities of directions a station no longer selects ([e382f73](https://github.com/g4bri3lDev/munich_public_transport/commit/e382f73c5f7005da777684622c61963bd2629ad6))
* show the transport type icon on departure sensors ([b7e6669](https://github.com/g4bri3lDev/munich_public_transport/commit/b7e666954f24431f4fcb2a10ed82acb6e1311047))
* give exception translations a message and drop manifest categories ([7b371d1](https://github.com/g4bri3lDev/munich_public_transport/commit/7b371d1ee7c2f6db8bc6dca679205220d1a0231e))


### Performance Improvements

* poll departures every minute ([9492878](https://github.com/g4bri3lDev/munich_public_transport/commit/9492878d997914c25bbf00353245bc61b6413753))

## [1.0.0](https://github.com/g4bri3lDev/munich_public_transport/compare/0.0.7...1.0.0) (2026-10-19)


### ⚠ BREAKING CHANGES

* Requires Home Assistant 2026.7.0 or newer (previously 2024.7.0).
* Existing stations are migrated automatically and keep their entity IDs, but entity unique IDs and some attributes changed. Templates reading attributes from 0.0.7 may need updating, and sensors for directions that no longer exist in MVG's schedule catalog are removed.


### Features

* migrate legacy station entries ([7c8baad](https://github.com/g4bri3lDev/munich_public_transport/commit/7c8baada3d963ea1cd01092f625eb48dd0a7daa2))
* restore service message sensors ([86e3c8a](https://github.com/g4bri3lDev/munich_public_transport/commit/86e3c8a2f74e6af6d4ada822d8433e11c4f175f4))
* rewrite integration with munich transport client ([ae89f25](https://github.com/g4bri3lDev/munich_public_transport/commit/ae89f250709727c12565e800b4bc7293cabdbdb1))


### Bug Fixes

* abort options flow instead of wiping selection when MVG is unreachable ([75d9095](https://github.com/g4bri3lDev/munich_public_transport/commit/75d90956d31e8cd95db6f47913f3afd92a65e2cc))
* derive direction options from departures for stations without abbreviation ([f66a44a](https://github.com/g4bri3lDev/munich_public_transport/commit/f66a44a84b08cdc37b6bc3999989cd138b58d12c))
* derive line sensor entity ids from the catalog terminus ([6f0beb4](https://github.com/g4bri3lDev/munich_public_transport/commit/6f0beb4b5e51aa722113a860b4f09a570cd6c326))
* remap legacy entities with the same fuzzy match as the direction selection ([9d9330c](https://github.com/g4bri3lDev/munich_public_transport/commit/9d9330cbcf30856614ecb73e42c98e63faeafd0a))
* remove legacy entities whose direction cannot be migrated ([f15939a](https://github.com/g4bri3lDev/munich_public_transport/commit/f15939a947e4bf9b50a2a8968ad1ea21be9b985e))
