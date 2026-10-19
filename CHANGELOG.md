# Changelog

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
