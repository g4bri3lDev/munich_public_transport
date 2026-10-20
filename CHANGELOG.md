# Changelog

## [2.0.0](https://github.com/g4bri3lDev/munich_public_transport/compare/1.0.0...2.0.0) (2026-10-20)


### ⚠ BREAKING CHANGES

* remove the station next departure sensor
* one disruption sensor per line and no delay or destination sensors
* remove the platform sensor
* one MVG entry with a subentry per station
* remove the station next departure sensor
* one disruption sensor per line and no delay or destination sensors
* remove the platform sensor
* one MVG entry with a subentry per station

### Features

* one disruption sensor per line and no delay or destination sensors ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* one disruption sensor per line and no delay or destination sensors ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))
* one MVG entry with a subentry per station ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* one MVG entry with a subentry per station ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))
* remove the platform sensor ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* remove the platform sensor ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))
* remove the station next departure sensor ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* remove the station next departure sensor ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))


### Bug Fixes

* give exception translations a message and drop manifest categories ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* give exception translations a message and drop manifest categories ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))
* remove entities of directions a station no longer selects ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* remove entities of directions a station no longer selects ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))
* show the transport type icon on departure sensors ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* show the transport type icon on departure sensors ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))


### Performance Improvements

* poll departures every minute ([15bc15b](https://github.com/g4bri3lDev/munich_public_transport/commit/15bc15b092ddb9e5e792e32faa319bdaa8f4d245))
* poll departures every minute ([2390db9](https://github.com/g4bri3lDev/munich_public_transport/commit/2390db977ed1622dba75f0597df39d130e9dec4f))

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
