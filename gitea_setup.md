# Self-hosted Linux and Windows test runners (Gitea Actions on TrueNAS)

Status: planned 2026-10-07, not set up yet.

Goal: run the test suite on Linux and Windows automatically on every push to
Gitea (`gitea.uklan`) while the TrueNAS server is up, without manual steps.

## Why Gitea Actions (not GitHub self-hosted runners)

- Development branches only go to Gitea, so that is where testing is wanted.
- Gitea Actions runs GitHub-style workflow files on self-hosted runners
  (`act_runner`). A runner polls Gitea for jobs, so nothing needs to be open
  to the internet.
- Self-hosted runners attached to the public GitHub repo could be made to run
  outside code on the home network. GitHub's hosted runners keep doing `main`
  and release tags (`.github/workflows/tests.yml`) as now.

## How it behaves when the server is off

- Gitea runs on the server, so a push simply isn't possible while it is down.
- If a runner VM is off when a push arrives, the job waits in the queue and
  runs when the runner comes up (Gitea abandons a waiting job after about
  24 h by default).

## Runners on TrueNAS (SCALE 24.10 or newer)

| | Linux | Windows |
|---|---|---|
| Where | TrueNAS app (Docker): `gitea/act_runner`, Docker mode, fresh Ubuntu 24.04 container per job. No VM needed. | VM: Windows 11 or Server, ~4 cores, 8 GB RAM, 80 GB disk. Install the VirtIO drivers during setup. |
| Runner | Registered with a token from Gitea, label `ubuntu-24.04` | `act_runner.exe` in host mode, run as a service that starts with Windows, label `windows` |
| Also needs | - | Python 3.12 and Git installed once |
| Start-up | App starts with TrueNAS | VM set to autostart |

Notes:
- The server is x86, so the vendored Linux ffmpeg/exiftool
  (`scripts/fetch_vendored_binaries.py`) works. The earlier Docker test on the
  Mac (arm64) had to fall back to Ubuntu's apt ffmpeg and exiftool 12.76,
  which fails two Tag Editor tests.
- The 14 GB `test_data/` can be shared read-only into both runners with
  `UWMEDIA_TEST_DATA` pointing at it. Then the `requires_media` tests, and
  the release tests (`tests/run_tests.sh 4`), run on Linux and Windows too.
  Nothing is copied into git.

## Workflow

Add `.gitea/workflows/tests.yml`. Gitea uses `.gitea/workflows/` instead of
`.github/workflows/` when it exists, so the GitHub workflow is unaffected.
Start from `.github/workflows/tests.yml` and change:

- Trigger: every branch push (plus optionally a nightly `schedule` running
  everything, `-m ""`, with `test_data/` mounted).
- Matrix: only the two self-hosted labels (`ubuntu-24.04`, `windows`);
  macOS is covered locally by the pre-commit hook.
- Env: `UWMEDIA_TEST_DATA` set to the mounted share.
- Results show in Gitea's Actions tab; Gitea can email on a failed run.

## Setup steps (about an hour)

1. Gitea: make sure Actions is enabled (`[actions] ENABLED = true` in
   `app.ini`; on by default since 1.21) and turned on for the repo
   (repo Settings > Actions).
2. Gitea: create a runner registration token (Site Administration or repo
   Settings > Actions > Runners).
3. TrueNAS: create the Linux runner app with the Gitea URL, token and label;
   mount the `test_data` dataset read-only.
4. TrueNAS: create the Windows VM, install Python 3.12, Git, `act_runner`;
   register it with the label `windows`; run it as a service; map the
   `test_data` share; set the VM to autostart.
5. Add `.gitea/workflows/tests.yml` (see above), push a branch to `gitea`
   and check that both jobs run.
6. Tick off "Windows and macOS runners" in `testing_plan.md` once results
   are in.

## Before starting

Gitea was unreachable on 2026-10-03, 10-04 and 10-06; runners can't pick up
jobs while it is down, so check why first. The pending pushes of 0.7.5 to
0.7.13 (main + tags) to `gitea` also need doing.
