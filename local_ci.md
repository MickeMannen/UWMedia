# Local CI: Gitea Actions with Linux, macOS and Windows runners

Investigation of 2026-10-16; nothing is set up yet. This extends
`gitea_setup.md` (Linux + Windows runners on TrueNAS, planned 2026-10-07)
with the macOS side and a phased plan for all three.

## 1. Goal

Every push of a development branch to Gitea (`gitea.uklan`, on the TrueNAS
server) runs the default test suite on Linux, macOS and Windows without
manual steps, and a nightly run does everything (release tests on the 4K
media, golden images). GitHub Actions keeps testing `main` and release tags
on its hosted runners (`.github/workflows/tests.yml`); release builds and
signing stay on GitHub (`build.yml`).

## 2. What exists

- GitHub: tests on macOS 15, Windows and Ubuntu for `main` and tags; manual
  release builds. Development branches never go there.
- Locally: the pre-commit hook runs the default suite on the owner's Mac
  (Apple M2, 16 GB, macOS 26.6).
- `gitea_setup.md`: Linux runner as a TrueNAS Docker app, Windows runner as
  a TrueNAS VM, workflow sketch, setup steps, and the note that Gitea was
  unreachable on several days in early October.
- `roadmap.md` §6 carries the open item for the runners (it came from the test-suite review in `docs/history/testing_plan.md`).

## 3. Constraints that shape the design

- **macOS can only be virtualised on Apple hardware.** Apple's macOS licence
  allows up to two additional copies of macOS to run as guests on each
  Apple-branded computer, and the Virtualization framework on Apple silicon
  refuses to boot a third macOS guest; Linux guests are not limited. A
  macOS VM on the x86 TrueNAS box would be a Hackintosh: against the
  licence and fragile. So the macOS runner lives on a Mac.
- **Windows must be x86** to match what users run and what `build.yml`
  builds (Briefcase on `windows-latest`). A Windows 11 ARM VM on the Mac
  would test a different Python and PySide6; the TrueNAS KVM VM (x86) is
  the right place.
- **Linux needs no VM**: the Docker-mode runner gives a fresh Ubuntu 24.04
  container per job on the x86 server, where the vendored ffmpeg and
  exiftool work (`scripts/fetch_vendored_binaries.py`).
- **Golden images depend on fonts** (`tests/test_template_golden.py`): the
  PNGs were made on the owner's Mac, so only the macOS runner compares them;
  Linux and Windows run `-m "not golden"` (the default already excludes
  them).
- **Private test data** (14 GB `test_data/`) stays out of git; runners that
  need it mount a read-only share and set `UWMEDIA_TEST_DATA`.
- **Gitea availability**: a runner only polls; if Gitea is down nothing
  runs, and a job waits in the queue while a runner is off (about 24 h).
  The outages noted in `gitea_setup.md` are the first thing to fix.

## 4. Options per platform

### Linux (recommended: Docker-mode runner on TrueNAS)

As in `gitea_setup.md`: TrueNAS app `gitea/act_runner`, Docker mode, label
`ubuntu-24.04`, `test_data` dataset mounted read-only. A VM would add
nothing. Ubuntu's apt exiftool is too old for two Tag Editor tests; the
job fetches the vendored binaries exactly as the GitHub workflow does.

### Windows (recommended: x86 VM on TrueNAS)

TrueNAS VM, Windows 11 (or Windows Server 2022 evaluation, 180 days and
re-armable), 4 cores, 8 GB, 80 GB, VirtIO drivers, Python 3.12, Git,
`act_runner.exe` as a service in host mode with the label `windows`,
`test_data` mapped read-only, autostart. Clean state: a ZFS snapshot of the
VM's zvol taken after setup, rolled back by a TrueNAS cron job nightly (or
before the nightly run), so stray files from a job never accumulate.
Windows runs its tests unactivated (a watermark only); whether to buy a
licence is the owner's call.

### macOS (recommended in two steps: host-mode runner on the Mac, then a Tart VM)

- **Step 1, host mode on the owner's Mac**: `act_runner` (darwin-arm64
  binary from the Gitea downloads) registered with the label
  `macos-arm64`, started as a `launchd` user agent. No VM, half an hour of
  work, the same fonts as the goldens. Downsides: jobs run on the
  development machine with its state, only while the Mac is awake, and a
  test run competes with whatever the owner is doing. Still the cheapest
  way to get a third platform into the matrix and it can stay as the
  fallback.
- **Step 2, a Tart VM on the Mac**: Tart (Cirrus Labs) builds and runs
  macOS guests on Apple silicon through the Virtualization framework and is
  royalty-free on personal computers under its Fair Source licence. Make a
  base image once (macOS, Xcode command line tools, Python 3.12, Git, the
  vendored binaries), then run jobs in clones: a small loop script keeps
  `act_runner` registered as an ephemeral runner inside a fresh clone,
  deletes the clone when the job ends and starts the next one. Each job
  starts clean, the development machine stays untouched. Cost: about 4
  cores and 8 GB while a job runs, which on a 16 GB M2 means a slower Mac
  for a minute per push; two macOS guests at most, so one runner VM.
- **Step 3, later, a dedicated Mac host** (a used Mac mini) running the Tart
  loop around the clock, which also removes the "Mac asleep" gap. Hardware
  cost; otherwise the same setup as step 2.

Ruled out: a macOS VM on TrueNAS (licence), GitHub self-hosted runners on
the home network (the public repo could run outside code locally).

## 5. Workflow design

`.gitea/workflows/tests.yml` (Gitea reads `.gitea/workflows/` and leaves the
GitHub workflow alone):

- Trigger: every branch push, plus `workflow_dispatch`, plus a nightly
  `schedule`.
- Matrix: `ubuntu-24.04`, `windows`, `macos-arm64`; `fail-fast: false`.
- Steps as the GitHub workflow: checkout, Python 3.12, Qt libraries on
  Linux, `pip install -r requirements.txt`, vendored binaries on PATH,
  `QT_QPA_PLATFORM=offscreen`, `python -m pytest -q`.
- The macOS job also runs `pytest tests/test_template_golden.py -m golden`.
- Nightly job: `UWMEDIA_TEST_DATA` pointing at the share, `tests/run_tests.sh 4`
  on each platform (release tests included), results mailed by Gitea on
  failure.
- A status badge from Gitea in the README is optional; the GitHub badge
  stays the public one.

## 6. Phases

| Phase | Work | Time | Done when |
|---|---|---|---|
| 0 | Find out why Gitea was unreachable and fix it; push the pending `main` and tags to `gitea`; check the Gitea version against the current `act_runner` (ephemeral runners need a recent Gitea) | 1-2 h | `git push gitea` works from the Mac on three different days |
| 1 | Linux runner app on TrueNAS, registration token, `.gitea/workflows/tests.yml` with the Linux job only | 1 h | a pushed branch shows a green Linux run in Gitea's Actions tab |
| 2 | macOS host-mode runner on the Mac (`launchd` agent, label `macos-arm64`), job added to the matrix, golden step | 1 h | green macOS run including the goldens |
| 3 | Windows VM on TrueNAS, runner service, job added, nightly snapshot rollback | 3 h | green Windows run; a file created by a job is gone the next morning |
| 4 | `test_data` share mounted on all three, nightly Everything run, failure mail | 1-2 h | the nightly run reports the same numbers as `tests/run_tests.sh 4` on the Mac |
| 5 | Tart base image and the ephemeral-clone loop on the Mac, replacing the host-mode runner (which stays registered as a fallback label) | half a day | two pushes in a row each run in a fresh clone |
| 6 | Later: Briefcase build jobs on the Windows and Linux runners to smoke-test installers on a clean VM (unsigned; signing stays on GitHub) | 1 day | the nightly run leaves a `.msi` and a `.deb` as artifacts |

Tick the runner item in `roadmap.md` after phase 3.

## 7. Risks

- Gitea down: nothing runs, and nothing tells you until a push fails. Put
  a simple uptime check on the TrueNAS box (phase 0).
- The Mac asleep or busy: host-mode jobs queue until it wakes; the Tart
  step and a dedicated host remove this.
- Resource pressure on a 16 GB Mac during a Tart job: keep the VM at 8 GB
  and 4 cores, one job at a time.
- Two macOS guests per Mac: one runner VM, never a second in parallel.
- Windows activation and updates: an unactivated VM is enough for tests;
  pause Windows Update during a run or let the nightly rollback undo it.
- Runner versions: `act_runner` must match the Gitea version's protocol;
  upgrade both together.

## 8. Decisions for the owner

1. macOS runner host: the development Mac (steps 1 and 2) or a dedicated
   Mac mini from the start?
2. Windows: unactivated Windows 11, Server evaluation, or a bought licence?
3. Nightly schedule time (the Everything run takes 7 minutes per platform,
   the 4K release tests read the share heavily).
4. Keep `gitea_setup.md` as the TrueNAS setup notes, or fold it into this
   file once the runners exist?

## References

- Apple's two-guest limit and its licence basis: https://eclecticlight.co/2022/08/04/virtualisation-on-apple-silicon-macs-8-how-apple-limits-vms/
- Tart (macOS and Linux VMs on Apple silicon, Fair Source, free on personal machines): https://alternativeto.net/software/tart/about and https://www.scaleway.com/en/docs/tutorials/run-manage-linux-vm-on-apple-silicon-tart.md
- Gitea `act_runner` labels and host mode, darwin builds on the Gitea downloads page: https://gitea.com/lgf/act_runner/src/branch/main/README.md
