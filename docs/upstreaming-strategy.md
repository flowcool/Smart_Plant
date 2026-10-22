# Upstream contribution strategy — flowcool/Smart_Plant → JGAguado/Smart_Plant

Owning roadmap: `infra-3rr`. Historical strategy issue: `infra-3rr.26`.
Historical publication and review owner: `infra-3rr.41`.

## Contribution history and publication decisions

The fork-first implementation and production validation are complete. Three
reviewable contributions rebuilt from `upstream/V2R1` were published on
2026-09-25; the fork's accumulated commit history remains evidence, not the
series to merge. Upstream merged PRs #27, #28 and #29 on 2026-10-20.

JGAguado accepted the Maintenance/Storage direction and offered `flowcool`
maintainership of the advanced work in upstream issue #24. The original plan
asked for explicit agreement on repository topology before publishing:

- preferred: one `V2R1` branch, the existing newcomer configuration kept as the
  default, and advanced material isolated under `examples/multi-device/`;
- fallback: a dedicated upstream branch, only if the maintainer still requires
  it and Florent accepts the resulting cross-branch maintenance cost.

A follow-up requesting that decision and proposing the PR series was posted on
2026-09-25: <https://github.com/JGAguado/Smart_Plant/issues/24#issuecomment-5838158797>.
Florent then removed the response gate and chose normal PR review as the
decision surface. `infra-3rr.21` was superseded by `infra-3rr.41`.

### Accepted contribution stack

All three PRs target upstream `V2R1`. GitHub cannot use a fork-owned branch as
the base of a PR in the upstream repository, so PR #28 and PR #29 temporarily
showed their predecessors too during review. Each body identified its one new
commit and linked an isolated comparison. The merge order was #27 → #28 → #29.

| PR | Durable scope | New commit |
| --- | --- | --- |
| [#27](https://github.com/JGAguado/Smart_Plant/pull/27) | Standalone baseline and documentation | `35ee343` |
| [#28](https://github.com/JGAguado/Smart_Plant/pull/28) | Shared core plus API/MQTT profiles | `a544250` |
| [#29](https://github.com/JGAguado/Smart_Plant/pull/29) | Generic sensor and e-paper lifecycle hardening | `8f4f75f` |

On 2026-10-20, Florent authorized separate fork PRs for low-battery protection
(`infra-3rr.31`) and Maintenance/Storage (`infra-3rr.40`). Both target
`flowcool/Smart_Plant:upstream/staging-v2r1`. This staging branch was created
from upstream commit `bcf373144b2d5c7e3a712fd02698e2e98e45aeed`. It keeps
contribution review separate from the deployed fork branch. This run does not
authorize new PRs to `JGAguado/Smart_Plant`.

## Historical preparation baseline

Historical audit snapshot before preparation:

- fork: `flowcool/Smart_Plant@V2R1`, commit `89a046e`;
- upstream target: `JGAguado/Smart_Plant@V2R1`, commit `b5d9ba4`;
- merge base: `890251b`;
- divergence: 130 fork commits and 2 upstream commits;
- tip-to-tip diff: 59 files, approximately 6,714 insertions and 383 deletions.

The two upstream commits are the merge and implementation of PR #25. Its image
syntax change is already present independently in the fork. Upstream PR #22
already established `examples/multi-device/` and an MQTT package on `V2R1`, so
the contribution is an evolution of accepted structure, not a new subsystem.

Never open a contribution PR from the long-lived fork branch. For the
2026-10-20 fork review decision, create each preparation branch from
`upstream/staging-v2r1`, port only its owned concern, and verify the resulting
diff independently. A later upstream publication needs its own authorization
and a fresh comparison with the latest fetched `upstream/V2R1`.

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

### Naming and screen-title contribution seam

`examples/multi-device/NAMING.md` explains stable identity, full human names,
function-only entity names and a separate short normal-page title. Use its
generic sections for a future contribution. The core's `screen_title` defaults
to `display_name`, so existing device overlays keep their previous behavior.
It has no effect on HA device names, MQTT identity or special display pages.

The 18-character/192-pixel check, local Audiowide copy, preview generator,
inventory overrides and generated device packages belong to the fork's fleet
tooling. They are not prerequisites for the generic core substitution. Do not
transfer the fleet examples or its historical registry migration as a required
upstream naming convention. Future publication still needs the fresh upstream
comparison and authorization described above.

## Recommended PR series

### PR 1 — Baseline documentation and standalone configuration (published #27)

Correct only behavior that already belongs to the upstream standalone path:

- MAX17048 automatic-hibernation guidance;
- the bounded single-cycle deep-sleep/OTA-validation flow;
- README and programming navigation to the already-present multi-device example.

Do not reference future profile filenames in this PR. Validate the standalone
YAML, build the Sphinx documentation, check links, and document compatibility.

### PR 2 — Shared core and transport profiles (published #28)

Replace the upstream MQTT-only base package with flat sibling composition:

- `smart_plant_core.yaml` for transport-independent hardware and lifecycle;
- `smart_plant_profile_api.yaml` for the simple native-API path;
- `smart_plant_profile_mqtt.yaml` for retained MQTT behavior;
- one thin, generic device overlay.

This PR owns structure, not later features. Prove the MQTT composition preserves
the upstream package behavior, compile both profiles, and keep the standalone
configuration as the newcomer entry point.

### PR 3 — Generic hardware and sensor hardening (published #29)

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

PRs #27-#29 were published as an ordered stack after Florent explicitly removed
the maintainer-response gate. Their upstream merges completed on 2026-10-20.
PR 4 and PR 5 use separate fork PRs under the authorization above. PR 5 depends
on PR 4. Each requires its own preparation and validation. Check Beads and GitHub
for current execution and review state.

No upstream merge authorizes a fork rebase, package-cache reset, compile, OTA,
or fleet deployment. Those remain separate state-changing operations with their
own Beads owner, canary, blast radius, and rollback.
