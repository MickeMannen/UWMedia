# Processing redesign: from CLI subprocess to a dedicated worker

Status: **draft 1** (2026-10-03). Findings and a recommendation, plus the work that has to be done before an implementation plan can be written. No code has changed. Items marked "to verify" have not been checked yet.

## 1. Summary

- The GUI's three processing pages (Color, Overlay Generator, Convertion) run their work by relaunching the app as a command-line run of `cli_main.py`, then reading progress back from its printed text.
- Recommendation: **keep processing in a separate child process, but replace the CLI interface with a dedicated worker.** The worker takes the job as JSON and reports back as JSON messages over a channel it controls.
- Moving the work into the GUI process (in a background thread) was considered and rejected, mainly because Stop and crash isolation get worse.
- Separate from this, and can happen first: drop the macOS `UWMedia-Terminal.pkg` installer. On Windows and Linux, `uwmedia-terminal` is the only build and stays as it is for now.

## 2. How processing runs today

- Each backend turns its UI state into CLI arguments (`_build_args`):
  - `uwmedia/backends/color_backend.py`
  - `uwmedia/backends/overlay_generator_backend.py`
  - `uwmedia/backends/convertion_backend.py`
- Settings that don't fit in a flag go into a temp file. For example, Color writes the overlay instances to `overlays.json` in `app_temp_dir()` and passes its path.
- `_build_command` starts the same binary with those arguments (`python -m uwmedia ...` from source, the bundled executable when packaged), through `QProcess`.
- `uwmedia/__main__.py` sends any run with arguments to `cli_main.main()`:
  - `cli_main.py` is 1505 lines, with 26 `argparse` options.
  - It runs files in parallel with a `ThreadPoolExecutor`.
  - It calls `ffmpeg/color.py`, the HUD renderer, exiftool and so on.
- Progress is plain text on stdout, which the backends parse line by line:
  - `UWMEDIA_PROGRESS <done>/<total> <status> <name>`: per-file completion (cli_main.py:461, 478, 502, 1381, 1405, 1409, 1425)
  - `UWMEDIA_PROGRESS_ACTIVE <name>`: a file has started (cli_main.py:1027)
  - `UWMEDIA_FFMPEG_PROGRESS <pct> [label]`: progress within the current file (cli_main.py:287, 753; `ffmpeg/color.py` `_FileProgress`; `ffmpeg/ffmpeg_class.py` `run_command`)
- Stop (`_kill_process_tree`) runs `pkill -9 -P <pid>` and then `QProcess.kill()`. A plain kill would leave the ffmpeg processes running.
- The `uwmedia/pages/*.py` copies of this logic belong to the older Widgets version and aren't used by the QML app. See the `uwmedia/app.py` docstring.

## 3. Problems with the current design

1. **The text protocol breaks silently.**
   - In 0.7.5 the macOS launcher (std-nslog) redirected the child's stdout to the system log. The pages got no progress lines at all and stayed at "Starting…" for the whole run. Fixed in 0.7.6 by restoring the original stdout/stderr for CLI runs.
   - Any stray `print`, buffering change, library writing to stdout, or launcher change can break progress the same way, with no error anywhere.
2. **Two layers to keep in sync.**
   - A new page option needs a CLI flag, argument building in the backend, and argument parsing and plumbing in `cli_main.py`.
   - Anything that doesn't fit in a flag needs a side file, like `overlays.json`.
3. **Errors only arrive as text.** The page gets an exit code, an `error <name>` status and loose stderr text, not a structured "file X failed at step Y because Z".
4. **Platform workarounds exist only because of this design.**
   - Windows: the app is a console app so one binary can be both the GUI and the CLI child. That forces the hidden-console relaunch (`_relaunch_gui_without_console_window` in `uwmedia/__main__.py`).
   - macOS: the stdio restore from 0.7.6.
5. **Stop probably doesn't work fully on Windows** (to verify).
   - `pkill` doesn't exist there; its failure is caught and ignored, so only the direct child is killed.
   - Running ffmpeg/exiftool processes are then left orphaned and keep writing output.
   - This is a bug on its own, whatever is decided here.
6. **Startup cost.** Every run starts Python again and re-imports everything (numpy, PIL, the dive and HUD modules) before any work begins. It's estimated at 1–2 s; to measure.

## 4. Options

### Option A: run the work in the GUI process (background thread)

Benefits:
- No protocol, argument building or stdio problems: progress and errors become direct Python callbacks or Qt signals.
- No startup cost per run.
- Windows could become a normal GUI app, with no console or relaunch trick. But see 6.3: ffmpeg/exiftool must still be started without console windows.
- Settings objects are shared directly; no temp files.

Costs:
- **Stop gets much harder.** A thread can't be killed. Every Python loop needs cancel checks, and every ffmpeg/exiftool process started anywhere in the pipeline has to be tracked and killed. Missing one leaves work running after Stop.
- **No crash isolation.** A segfault or memory blow-up in a native library (numpy, PIL, OpenCV, pyexiftool) during a long batch closes the whole app, not just the run.
- **The UI may stutter.** Colour analysis and HUD drawing hold Python's global lock (GIL) part of the time, which competes with the UI thread. Probably small; to measure.
- **Memory never fully returns.** Leaks or caches in a long run stay in the GUI process until the app is closed.
- **Biggest change:** all three backends, plus making the pipeline cancellable throughout.

### Option B (recommended): keep a child process, with a dedicated worker

- **A new entry point**, e.g. `uwmedia/worker.py`, started as `<app> --worker`:
  - It reads one **job spec** (JSON) from a file or stdin.
  - It calls the pipeline functions directly (`process_video`, `process_single_file`, the conversion and overlay-generator paths) without going through `argparse`.
- **Messages are JSON lines** on a channel the worker opens itself, so launchers or stray prints can't redirect it.
  - The channel could be an extra pipe, a local socket (`QLocalSocket`), or a file descriptor passed in (to decide, see 6.2).
  - Message types, for example: `run_start`, `file_start`, `file_progress {pct, phase, label}`, `file_done {status, output, stats}`, `file_error {file, step, message}`, `run_done {summary}`, `log {level, text}`.
- **The backend writes the job spec straight from page state.** No argument strings, no `overlays.json`. One shared parser handles all three pages.
- **Isolation stays.** Stop still kills a process, and a native crash only fails the run. Stop is fixed properly at the same time:
  - macOS/Linux: a process group (`start_new_session`), killed with `killpg`.
  - Windows: a job object, or `taskkill /T /F`.
- **`cli_main.py` becomes optional for the GUI.** Keep it as a thin wrapper that builds the same job spec from arguments, for scripting and running from source. Delete it later if it isn't needed.

Costs:
- New code: the worker entry point, the job spec, the message channel, and a shared client on the GUI side.
- During the migration, both the old and the new path exist for a while (one page at a time).
- The startup cost per run stays (see 6.5).

### Why B over A

B removes problems 1–4 and fixes 5, while keeping what the subprocess design already does well: reliable Stop and crash isolation. A gives up both of those in exchange for saving the startup time.

## 5. Related decisions

- **Drop the macOS Terminal installer (independent, can go first).** Remove `uwmedia-terminal.macOS` from `pyproject.toml`, the two macOS `uwmedia-terminal` entries in `.github/workflows/build.yml`, the macOS Terminal step in `build.sh`, and the `UWMedia-Terminal-*.pkg` part of `docs/getting-started.md`. It's untested, and it already behaves differently from the main app. Scripting stays possible from source.
- **Windows/Linux `uwmedia-terminal`:** unchanged for now. Once the worker exists, decide whether it can become a GUI-subsystem app (6.3).
- **The Flutter port (`investigation.md`).** If the port goes ahead, Python processing would be replaced by Dart/ffmpeg, and this redesign is only worth what it fixes before then. But a job spec plus JSON messages is also the natural interface between a Flutter desktop shell and a Python worker, if the port keeps Python processing on desktop for a while. Decide this first (6.1).

## 6. Work before an implementation plan

These must be answered or measured first; each one changes the plan.

### 6.1 Decisions (owner)
- [ ] Is the Flutter port going ahead, and roughly when? If it's soon, limit this to the Stop fix plus the Terminal installer removal.
- [ ] Is `cli_main.py` kept as a supported scripting tool (thin wrapper over the job spec), kept for source/tests only, or removed?
- [ ] Are the Windows/Linux builds expected to stay console apps?

### 6.2 Investigations (code)
- [ ] **Full inventory of the CLI options in use.** For each of the 26 options: which page sets it, and which pipeline function finally reads it. This gives the job spec's fields and shows dead options.
- [ ] **Map how `args` flows through `cli_main.py`.** `process_single_file`, `process_log_only`, `process_conversions` and others take the whole `argparse` namespace; list every attribute they read. Decide whether the worker passes a typed spec (dataclass/pydantic) or an adapter that looks like `args`.
- [ ] **Inventory every print to stdout/stderr in the pipeline** (`cli_main.py`, `ffmpeg/`, `metadata/`, `gui/hud_renderer.py`, tqdm). Each one becomes a message, a log line, or is removed.
- [ ] **List what the three backends parse today.** Statuses, error handling, timing, the "N of M files done" text, and the final summary. The new messages must cover all of it, or the pages lose information.
- [ ] **Choose the message channel.** Extra pipe vs `QLocalSocket` vs a passed fd: check what works the same way on macOS, Windows and Linux with `QProcess`, in both source and packaged builds.
- [ ] **Find everywhere external processes are started** (ffmpeg, ffprobe, exiftool via pyexiftool, anything else), for the process-group / job-object Stop fix.
- [ ] **Check the existing tests.** Which ones drive the CLI (`tests/` has 49 files) and how they would move to the job spec or worker.

### 6.3 Verifications (run it)
- [ ] **Windows Stop:** start a Color video run, press Stop, and check Task Manager for ffmpeg still running. Do the same with Overlay Generator and Convertion.
- [ ] **Windows console:** does a GUI-subsystem build that starts a child (with `CREATE_NO_WINDOW`) and ffmpeg/exiftool show any console windows? This decides whether the relaunch trick can go.
- [ ] **Packaged macOS:** confirm that an extra pipe or socket survives Briefcase's launcher, which is exactly the kind of thing that broke stdout.

### 6.4 Measurements
- [ ] Child startup time to its first progress line, from source and packaged, on macOS and Windows. Decides whether 6.5 matters.
- [ ] Optional, only if A is reconsidered: UI frame-time while colour analysis and HUD drawing run in a thread of the GUI process.

### 6.5 Open question
- [ ] Keep one long-lived worker per app session (no startup cost after the first run, but Stop then needs cancel-in-worker plus a kill fallback), or start one worker per run (simpler; same as today)? Decide after 6.4.

## 7. After this: the implementation plan

Once section 6 is done, write the plan as separate, shippable steps:
1. Fix Windows Stop (process tree kill on all platforms).
2. Remove the macOS Terminal installer.
3. Job spec, worker entry point and message channel, with tests.
4. Move Color to the worker, then Overlay Generator, then Convertion. One page per release, with the old path removed after each.
5. Make `cli_main.py` a thin wrapper, or remove it (per 6.1).
6. Reconsider the Windows/Linux console app (per 6.3).
