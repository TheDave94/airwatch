# Changelog

## 1.0.0 (2026-06-19)


### ⚠ BREAKING CHANGES

* drive severity from the revised WHO-aligned EEA index

### Features

* **brand:** AirWatch visual identity adapted from PollenWatch ([70620fb](https://github.com/TheDave94/airwatch/commit/70620fb4350fca763ba38d6ee3b286d0793a1432))
* **card:** build the AirWatch Lovelace card ([26c82dd](https://github.com/TheDave94/airwatch/commit/26c82dd4029019c1887d95277e31c161afeebe40))
* **card:** restyle the Lovelace card to the AirWatch design system ([88ddcef](https://github.com/TheDave94/airwatch/commit/88ddcef957c6df1a0c842b93aeab6a6d6f9dea3e))
* data layer — source contract, pollutant registry, analytics, Open-Meteo ([8836ba6](https://github.com/TheDave94/airwatch/commit/8836ba6d6960ff0f6776aa76d903e8ab13c29166))
* drive severity from the revised WHO-aligned EEA index ([4ef7143](https://github.com/TheDave94/airwatch/commit/4ef7143a4c54fadef0cad488fdfdccfcfd1e9306))
* full provenance-tagged thresholds (WHO 2021 + EU 2024/2881 + EEA) ([08b2922](https://github.com/TheDave94/airwatch/commit/08b29220ea6712827a0e4b5973d31cadb7fa862f))
* Home Assistant integration — coordinators, entities, config flow ([303eb49](https://github.com/TheDave94/airwatch/commit/303eb49c7d374b55d12035d86f7d6912ade0b170))
* Land Steiermark drift-anchor source (SensorThings, lag-aware) ([0770805](https://github.com/TheDave94/airwatch/commit/0770805dd65867e21bdb1497c4fcfb80b1a58dc7))
* make Land Steiermark selectable in config + options flow ([e182fba](https://github.com/TheDave94/airwatch/commit/e182fbac36834112d2d8a2cffe407f5b1629c94a))
* make Sensor.Community selectable in config + options flow ([dc395fc](https://github.com/TheDave94/airwatch/commit/dc395fc875c150ad1c5e36e62511af271f5b1448))
* provenance hardening — EU overlay, EAQI averaging, structured bands ([25c9090](https://github.com/TheDave94/airwatch/commit/25c9090690c35eb0dfeae18413793557f34a3407))
* Sensor.Community secondary source (fault-rejecting, consensus-ready) ([9705d09](https://github.com/TheDave94/airwatch/commit/9705d0964f50ffb31acebf5572008003ceb4ac95))
* ship inline brand icons (HA 2026.3+ brands proxy) ([10bd420](https://github.com/TheDave94/airwatch/commit/10bd4207c97d0246ab7bfe9544d6e4d98561b394))


### Bug Fixes

* **card:** pollutant-name wrapping + theme-derived text colour ([5b6e2b7](https://github.com/TheDave94/airwatch/commit/5b6e2b74a8a9aa9b39d6d30d1466912e99c9f96d))
* **card:** tighten gauge assembly + header/spacing/callout placement ([979efef](https://github.com/TheDave94/airwatch/commit/979efef656c9d37466549577313ac06441d405a5))
