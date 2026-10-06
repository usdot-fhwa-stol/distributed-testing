### Distributed Testing
----------------------------

## Version 2.0.0, released Sep 30th 2026

### Summary
In this release, Distributed Testing adds automated Docker builds and GitHub workflows, TENA V2X Hub build environment automation, SIMDIS integration, and updates to the HASS DT work zone development images and scenario configuration.

**Enhancements**

- Automate TENA V2X Hub build environment creation with full runtime support, and add GitHub workflows and automated Docker builds split by dependency.
  * Pull Requests: [distributed-testing PR #83](https://github.com/usdot-fhwa-stol/distributed-testing/pull/83), [distributed-testing PR #86](https://github.com/usdot-fhwa-stol/distributed-testing/pull/86), [distributed-testing PR #102](https://github.com/usdot-fhwa-stol/distributed-testing/pull/102)

- Add the SIMDIS Dockerfile for HASS and SIMDIS and yield integration testing changes.
  * Pull Requests: [distributed-testing PR #72](https://github.com/usdot-fhwa-stol/distributed-testing/pull/72), [distributed-testing PR #81](https://github.com/usdot-fhwa-stol/distributed-testing/pull/81)

- Update the HASS DT work zone development image to the 6.0.11 SDK, update the V2X Hub Dockerfile to V2X Hub develop, and add the V2X Hub V2X plugin Docker build.
  * Pull Requests: [distributed-testing PR #63](https://github.com/usdot-fhwa-stol/distributed-testing/pull/63), [distributed-testing PR #74](https://github.com/usdot-fhwa-stol/distributed-testing/pull/74), [distributed-testing PR #88](https://github.com/usdot-fhwa-stol/distributed-testing/pull/88)

- Install the STOL J2735 deb package in the Dockerfile and update to the J2735 2024 version.
  * Pull Requests: [distributed-testing PR #76](https://github.com/usdot-fhwa-stol/distributed-testing/pull/76), [distributed-testing PR #77](https://github.com/usdot-fhwa-stol/distributed-testing/pull/77)

- Add a staleSdsmThreshMs option to the start-entity-generator script, and update scenario XML and Docker-related settings.
  * Pull Requests: [distributed-testing PR #101](https://github.com/usdot-fhwa-stol/distributed-testing/pull/101), [distributed-testing PR #105](https://github.com/usdot-fhwa-stol/distributed-testing/pull/105)

- Update configurations for dth2, add a testing script from develop, and add PC configuration for HASS-639.
  * Pull Requests: [distributed-testing PR #65](https://github.com/usdot-fhwa-stol/distributed-testing/pull/65), [distributed-testing PR #66](https://github.com/usdot-fhwa-stol/distributed-testing/pull/66)

**Fixes**

- [distributed-testing PR #108](https://github.com/usdot-fhwa-stol/distributed-testing/pull/108): Fix the verification issuer.

- [distributed-testing PR #104](https://github.com/usdot-fhwa-stol/distributed-testing/pull/104): Update the threads library and UDP protocol IO dependencies to pull the correct branches.

- [distributed-testing PR #97](https://github.com/usdot-fhwa-stol/distributed-testing/pull/97): Remove the runtime build target.

- [distributed-testing PR #98](https://github.com/usdot-fhwa-stol/distributed-testing/pull/98): Fix and update the CI action.

- [distributed-testing PR #91](https://github.com/usdot-fhwa-stol/distributed-testing/pull/91): Fix the version bump.

**Other Updates**

- [distributed-testing PR #106](https://github.com/usdot-fhwa-stol/distributed-testing/pull/106): Add release branch and version tag triggers to CI.

### VUG Entity Generator

In this release, VUG Entity Generator adds VRU LVC entity support and stale SDSM entity pruning, and updates to the J2735 2024 standard.

**Enhancements**

- Add the VRU LVC entity.
  * Pull Requests: [vug-entity-generator PR #14](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/14)

- Prune stale SDSM entities after a time threshold.
  * Pull Requests: [vug-entity-generator PR #27](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/27)

- No longer request shutdown on thread error; log a warning and skip processing instead.
  * Pull Requests: [vug-entity-generator PR #26](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/26)

- Update the STOL J2735 version to the 2024 standard.
  * Pull Requests: [vug-entity-generator PR #17](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/17)

**Fixes**

- [vug-entity-generator PR #20](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/20): Fix the coordinate convention.

- [vug-entity-generator PR #22](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/22): Fix the offset_z type.

**Other Updates**

- [vug-entity-generator PR #24](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/24), [vug-entity-generator PR #25](https://github.com/usdot-fhwa-stol/vug-entity-generator/pull/25): Update versions to support the 6.0.11 SDK.

### VUG V2X Hub V2X Plugin

In this release, the VUG V2X Hub V2X Plugin is built against the V2X Hub develop branch, adds host network support, and adds development container support for the new DT V2X Hub images.

**Enhancements**

- Build the V2X Hub TENA V2X plugin using the develop branch of V2X Hub as a base.
  * Pull Requests: [vug-v2xhub-v2x-plugin PR #7](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/7)

- Use the host network for V2X Hub.
  * Pull Requests: [vug-v2xhub-v2x-plugin PR #17](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/17)

- Support development container setup for the new dt-v2xhub and dt-build-v2xhub images.
  * Pull Requests: [vug-v2xhub-v2x-plugin PR #16](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/16)

**Fixes**

- [vug-v2xhub-v2x-plugin PR #12](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/12): Fix the TENA V2X plugin networking issue.

- [vug-v2xhub-v2x-plugin PR #13](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/13): Fix payload bytes being copied from the full length buffer.

- [vug-v2xhub-v2x-plugin PR #15](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/15): Fix the integration test.

**Other Updates**

- [vug-v2xhub-v2x-plugin PR #19](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/19), [vug-v2xhub-v2x-plugin PR #20](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/20): Update versions to support the 6.0.11 SDK.

- [vug-v2xhub-v2x-plugin PR #25](https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin/pull/25): Update the repository for the Wrangler release.

### VUG Scenario Publisher

In this release, VUG Scenario Publisher is updated to support the 6.0.11 SDK.

**Other Updates**

- [vug-scenario-publisher PR #13](https://github.com/usdot-fhwa-stol/vug-scenario-publisher/pull/13), [vug-scenario-publisher PR #14](https://github.com/usdot-fhwa-stol/vug-scenario-publisher/pull/14): Update versions to support the 6.0.11 SDK.

### VUG V2X Adapter

In this release, VUG V2X Adapter is updated from the 6.0.9 SDK to the 6.0.11 SDK.

**Other Updates**

- [vug-v2x-adapter PR #9](https://github.com/usdot-fhwa-stol/vug-v2x-adapter/pull/9), [vug-v2x-adapter PR #10](https://github.com/usdot-fhwa-stol/vug-v2x-adapter/pull/10): Update versions from the 6.0.9 SDK to the 6.0.11 SDK.