# Upstream contribution strategy — flowcool/Smart_Plant → JGAguado/Smart_Plant

Owning roadmap: `infra-3rr`. Architecture gate: `infra-3rr.21`. Historical
strategy issue: `infra-3rr.26`.

## Status

The fork-first implementation and production validation are complete. Work now
targets a reviewable contribution series rebuilt from the current
`upstream/V2R1`; the fork's accumulated commit history is evidence, not the
series to merge.

JGAguado accepted the Maintenance/Storage direction and offered `flowcool`
maintainership of the advanced work in upstream issue #24. The remaining gate
is explicit agreement on repository topology:

- preferred: one `V2R1` branch, the existing newcomer configuration kept as the
  default, and advanced material isolated under `examples/multi-device/`;
- fallback: a dedicated upstream branch, only if the maintainer still requires
  it and Florent accepts the resulting cross-branch maintenance cost.

A follow-up requesting that decision and proposing the PR series was posted on
2026-09-25: <https://github.com/JGAguado/Smart_Plant/issues/24#issuecomment-5838158797>.

## Current baseline

Audit snapshot before preparation:

- fork: `flowcool/Smart_Plant@V2R1`, commit `89a046e`;
- upstream target: `JGAguado/Smart_Plant@V2R1`, commit `b5d9ba4`;
- merge base: `890251b`;
- divergence: 130 fork commits and 2 upstream commits;
- tip-to-tip diff: 59 files, approximately 6,714 insertions and 383 deletions.

The two upstream commits are the merge and implementation of PR #25. Its image
syntax change is already present independently in the fork. Upstream PR #22
already established `examples/multi-device/` and an MQTT package on `V2R1`, so
the contribution is an evolution of accepted structure, not a new subsystem.

Never open a PR from the long-lived fork branch. Create each preparation branch
from the latest fetched `upstream/V2R1`, port only its owned concern, and verify
the resulting diff independently.

## Contribution boundary

Upstream-worthy:

- corrections to the standalone example and user-facing programming docs;
- shared core plus native-API and MQTT transport profiles;
- transport-independent sensor, I2C, e-paper, ADC, and lifecycle hardening;
- configurable low-battery protection and display states;
- retained MQTT Maintenance and Storage modes with bounded recovery;
- a generic multi-device guide and thin example overlay.

Fork-only:

- the real eight-device `plants.yaml` inventory, generated device metadata, IP
  addresses, botanical naming history, and Home Assistant registry migrations;
- Device Builder/NAS/VPS fleet automation and local MQTT helper scripts;
- `.claude`, `AGENTS.md`, `CLAUDE.md`, Beads references, and homelab commands;
- plant-specific artwork and threshold snapshots;
- the removed pull-OTA implementation and its historical evaluation.

The current `examples/multi-device/README.md` deliberately contains both generic
package documentation and flowcool fleet operations. Do not copy it wholesale
upstream: extract a short generic guide and leave deployment operations here.

## Recommended PR series

### PR 1 — Baseline documentation and standalone configuration

Correct only behavior that already belongs to the upstream standalone path:

- MAX17048 automatic-hibernation guidance;
- the bounded single-cycle deep-sleep/OTA-validation flow;
- README and programming navigation to the already-present multi-device example.

Do not reference future profile filenames in this PR. Validate the standalone
YAML, build the Sphinx documentation, check links, and document compatibility.

### PR 2 — Shared core and transport profiles

Replace the upstream MQTT-only base package with flat sibling composition:

- `smart_plant_core.yaml` for transport-independent hardware and lifecycle;
- `smart_plant_profile_api.yaml` for the simple native-API path;
- `smart_plant_profile_mqtt.yaml` for retained MQTT behavior;
- one thin, generic device overlay.

This PR owns structure, not later features. Prove the MQTT composition preserves
the upstream package behavior, compile both profiles, and keep the standalone
configuration as the newcomer entry point. Opening it is gated by issue #24.

### PR 3 — Generic hardware and sensor hardening

Port only transport-independent corrections:

- switched-I2C rail settling and deterministic acquisition ordering;
- per-sensor acquisition cadence independent of soil median filtering;
- unavailable/NaN rendering guards;
- implausible ADC-voltage rejection before soil calibration;
- bounded e-paper BUSY observation and recovery;
- an explicit, separately explained captive-portal/web-OTA decision.

Validate both profiles. Do not include low-battery policy or retained MQTT modes.

### PR 4 — Low-battery protection

Port the NVS latch, WARN inversion, CRITICAL page, configurable thresholds,
hysteresis, and protective long sleep. The feature remains transport-neutral.
Reuse the existing eight-device field evidence without repeating fleet rollout;
add deterministic boundary tests and visual examples suitable for review.

### PR 5 — Advanced MQTT Maintenance and Storage

Port the retained request/effective-status contract, priority
`Maintenance > Storage > Normal`, battery admission, bounded watchdog, OTA
cleanup, Storage persistence, and daily battery-only wake. Keep every MQTT
reference in the MQTT profile. Document the protocol without prescribing the
flowcool Home Assistant implementation.

## Review and validation contract

Every PR must provide:

1. exact upstream base SHA and ordered commit list;
2. motivation, scope, exclusions, and compatibility impact;
3. semantic diff plus `git diff --check` and line-ending review;
4. YAML parse/configuration evidence for every affected composition;
5. compile evidence when firmware behavior changes;
6. existing physical validation references, with no unapproved production test;
7. rollback before merge (close PR/delete branch) and after merge (revert the
   isolated commit/PR; no automatic fleet deployment);
8. documentation build and link check for changed public docs.

One monolithic PR is the fallback only if the maintainer explicitly requests
it. Even then, preserve the five concerns as ordered, independently reviewable
commits and provide the same evidence matrix per commit.

## Sequencing

Local documentation/test convergence and the upstream delta inventory may run
while issue #24 awaits a response. PR 1 can be prepared independently because it
does not assume the profile topology. PR 2 and every dependent PR may be
prepared locally but must not be opened until the topology gate is resolved.

No upstream merge authorizes a fork rebase, package-cache reset, compile, OTA,
or fleet deployment. Those remain separate state-changing operations with their
own Beads owner, canary, blast radius, and rollback.
