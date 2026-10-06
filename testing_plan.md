# Testing plan

Working doc for the test-suite review started 2026-10-06 on the
`verification` branch. Tick items off as they land; add findings at the end.

## Rules for anything that goes into git (owner decisions, 2026-10-06)

- **Photos and videos:** the owner reviews every photo and video before it is
  committed or pushed. Claude prepares candidates in the scratchpad (or an
  ignored folder), lists them with size and content, and waits for an OK per
  file. Nothing media goes into `tests/fixtures/` without that OK.
- **Dive logs are never committed.** FIT, UDDF, SSRF, Shearwater XML/CSV and
  other dive-profile files carry device serial numbers and personal IDs.
  Tests that need a log in git-tracked form must build a synthetic one at
  test time with the app's own writers (`parsers/fit_writer.py`, the UDDF and
  SSRF writers) from `utils/dummy_telemetry.py`-style data, or be marked
  `requires_media` and run only where `test_data/` exists.
- Check exported fixtures for metadata too: EXIF/XMP on photos and videos can
  hold camera serial numbers, owner names and GPS. Strip or confirm with the
  owner as part of the review.
- Already tracked and OK: `tests/deco_reference/` (Subsurface planner output,
  no device or personal data).

## Fixture layout (agreed 2026-10-06)

Tracked test data lives in `tests/fixtures/` (target total ~5 MB, plain git):

```
tests/fixtures/
  README.md          one row per file: what, source, how cut/scaled, metadata
                     kept/stripped, reviewed by owner + date
  media/video/       h264_8bit_720p_2s.mp4, h264_10bit_422_720p_2s.mp4
  media/photo/       jpeg_3x2_2mp.jpg (+ others only if a test needs them)
```

- Names describe the property a test needs, not the source file.
- No dive logs: tests that need one get a synthetic log written into
  `tmp_path` by the app's own writers (a conftest fixture).
- `tests/deco_reference/` stays where it is.
- `test_data/` stays in the repo folder (git-ignored) for now; it still
  feeds `release_test.py` (full 4K media) and the `requires_media` tests
  (real-format logs). Cleanup later - options then: move it outside the repo
  and point `UWMEDIA_TEST_DATA` at it, or delete it and accept those tests
  skipping. Anonymised real logs in git: not planned unless the owner decides
  otherwise.

## Decisions (owner, 2026-10-06)

1. Small media fixtures in git under `tests/fixtures/`: yes (after review, see
   rules above).
2. Default `run_tests.sh` run is the fast suite: yes.
3. CI on GitHub for `main` and tag pushes: yes.
4. Delete the old output in `test_data/test_results` (4.8 GB): yes.
5. Keep `release_test.py` as a separate pre-release run on the real 4K media:
   yes.

Order: Phase 1, 3, 2, 4, 5, 6.

## Baseline (2026-10-06, macOS, single process)

653 passed, 3 xfailed in 22m11s. About 20 render tests take about 20 min
(90%); the other ~635 take about 1.5 min.

| File | Time | Why |
|---|---|---|
| test_color_multi_overlay.py | 494 s | 2 full 4K renders, ~4 min each |
| release_test.py | 324 s | 14 CLI runs on full 4K clips and 20 MB JPEGs |
| test_color.py | 238 s | `test_color_and_layout_video` renders all 5 overlay zips (201 s) |
| test_hud_layers.py | 112 s | full render + `ffprobe -count_frames` |
| test_convert.py | 32 s | 4K -> 1080p |
| test_metadata.py | 19 s | CLI runs on 20 MB photos |
| everything else | ~90 s | |

Source clips are 10 s 4K (82 MB DJI, 253 MB 10-bit 4:2:2 Sony); the render
tests don't need that much video.

## Findings

1. `test_data/` (14 GB) is git-ignored, so ~18 test files only run on the
   owner's Mac; CI runs no tests at all.
2. `test_data/test_results` holds 4.8 GB of accumulated output; most tests
   write there instead of `tmp_path`.
3. Not parallel-safe: `test_color.py`'s cleanup glob `test_color_*` also
   deletes `test_color_multi_overlay_*` and `test_color_preview_tmp/`;
   `temp_render_video_log_input` and `release_test`'s session cleanup are
   fixed paths.
4. Dead / misnamed: `tests/tests_windows.py` (never collected, its input video
   doesn't exist, module fixture would run ffmpeg on any OS);
   `tests/generate_readme_content.py` (a script -> `scripts/`);
   `tests/release_test_prompt.txt` (stray); `test_metadata.py`
   `test_datetaken` / `test_debug_datetaken` (debug scripts, hard-code
   `/Users/mikael/DivingMedia`, assert nothing).
5. `release_test.py` runs in every plain `pytest`; its docstrings promise 1 s
   segments that are never used; `test_06b` checks 0 == 0; most of it repeats
   other tests.
6. Fragility: subprocess calls use `"python3"` instead of `sys.executable` and
   rely on cwd = repo root; module caches (`_font_cache`, font registry
   `lru_cache`, rules/timeline caches) never reset; `BASE_DIR` / results-dir
   fixtures / backend builders copied across 6-8 files.
7. `run_tests.sh` lists were stale and option 1 claimed "Unit + Pre-release"
   while being a plain run.
8. The 3 xfails (`test_deco_reference.py`: `air_long_deco`, `nx32_deco`,
   `air_multi_deco`): the Subsurface reference plans carry tissue load from an
   earlier dive; re-plan them in Subsurface with no previous dive.

### Coverage gaps (riskiest first)

1. `ffmpeg/color.py` - only "a file came out" is checked, never filter values.
2. `utils/color_profiles.py`, `utils/color_params.py`,
   `uwmedia/backends/color_tuning_backend.py` - no tests.
3. Tag Editor (`uwmedia/backends/tag_editor_backend.py`, `utils/tag_editor.py`)
   rewrites user files' metadata - 3 helpers tested.
4. `ffmpeg/ffmpeg_class.py` command building / hw-accel - thin.
5. `cli_main.py`: `get_unique_path`, `generate_fcpxml`, parallel worker,
   `print_summary` - none.
6. QML: nothing loads a `.qml` file; `pyside6-qmllint` installed but unused.
7. `utils/tool_paths.py`, `utils/config.py`, `utils/dive_plan_import.py`,
   Windows/Linux path resolution in `utils/resource_paths.py` - none / thin.

## Phases

### Phase 1 - fast default run (done 2026-10-06)
- [x] `[tool.pytest.ini_options]` in `pyproject.toml`: `testpaths`,
      `pythonpath` (no more `PYTHONPATH=.`), markers `render` and `release`,
      default `-m "not render and not release"`.
- [x] Marked 13 render tests `render` (`test_color.py`, `test_render_log.py`,
      `test_render_video_log.py` whole modules; two in
      `test_color_multi_overlay.py`; one each in `test_hud_layers.py` and
      `test_convert.py`; three CLI tests in `test_metadata.py`) and
      `release_test.py` `release`.
- [x] `run_tests.sh` menu: 1 Fast (Enter = default) / 2 Full (fast + renders)
      / 3 Release / 4 Everything. Without a terminal and no argument it now
      exits instead of spinning on the prompt forever.
- [x] `test_color.py` cleanup only deletes its own outputs.
- [x] Fast run: 625 passed, 28 deselected, 3 xfailed in 1m40s (was 22m11s
      for everything). Selection counts: fast 628, full 641, release 15,
      everything 656.
- [x] Owner decided: a release needs option 4 (everything);
      CLAUDE.md's release check says so.

### Phase 3 - clean up (2026-10-06)
- [x] Test output to `tmp_path` everywhere except `release_test.py`, whose
      outputs stay in `test_data/test_results/release_test` for a look
      afterwards (replaced each run). Deleted the old 4.7 GB in
      `test_data/test_results`.
- [x] `conftest.py`: `TEST_DATA` (override with `UWMEDIA_TEST_DATA`),
      `RELEASE_MEDIA`, `LOGS_DIR`, and `run_cli()` (this interpreter, not
      `python3`; cwd = repo root). No test builds a `test_data/...` path
      itself or calls `python3` any more.
- [x] `requires_media` marker on the 51 non-render tests that read
      `test_data/` (found by running with `UWMEDIA_TEST_DATA` pointing at a
      missing folder); `render`, `release` and `requires_media` tests skip
      when `test_data/` is missing. Without media: 575 passed, 52 skipped,
      0 failed.
- [x] Module caches: checked, no reset needed (`_timeline_cache` holds the
      waypoint list it is keyed on, the rules and font caches only read
      files that tests never change).
- [x] Backend builders (`make_fake_backend` etc.): kept per file - each sets
      the attributes its own feature needs; no common subset worth sharing.
- [x] `tests_windows.py` -> `test_windows.py` (now collected; `windows`
      marker, skipped off Windows; uses the release_test media and a 2 s cut
      in `tmp_path`, no module fixture writing into `test_data/`);
      `generate_readme_content.py` -> `scripts/`; removed
      `release_test_prompt.txt`; removed the two debug "tests" in
      `test_metadata.py`.
- [x] `release_test.py`: kept every render (after Phase 2 it is the only
      run on the full 4K media); removed the vacuous `test_06b`; fixed the
      docstrings that promised 1 s segments; failures now show the CLI's
      stderr.
- [x] Found while converting: `test_uddf.py`'s `test_parse_atmos_uddf` and
      `test_parse_perdix_uddf` had silently passed without testing anything
      (their files had moved; the tests returned early when a file was
      missing). They now use the right paths and pass for real.
- [x] `test_convert_resolution_replacement_naming` tested its own copy of
      the naming code; it now tests the Convertion backend's real
      `_convert_output_filename`.
- [x] Phase 6 note: `cli_main.py`'s `--convert` repeats that naming code
      inline instead of sharing it with the backend. Done in Phase 6
      (`utils/convert_naming.py`).

### Phase 2 - small test media (2026-10-06)
- [x] `scripts/make_test_fixtures.py` builds 2 s 720p clips (Sony 10-bit
      4:2:2 H.264, DJI HEVC Main 10) and a 1800x1200 JPEG from
      `test_data/release_test`: all metadata stripped, only an allowlist of
      date / time-zone / make-model tags copied back. 2.6 MB in all. Owner
      reviewed pictures and metadata; record + SHA-256 in
      `tests/fixtures/README.md`.
- [x] Synthetic dive logs: `write_synthetic_log()` (UDDF / FIT / SSRF via
      the app's writers) and the session fixture `synthetic_logs` (UDDF
      dives covering every fixture clip and photo) in `tests/conftest.py`.
- [x] All render tests use the fixtures + synthetic logs; the overlay tests
      also assert the dive was matched (the CLI writes an output file even
      when no dive matches). `render` no longer needs `test_data/`;
      `release_test.py` keeps the full 4K media.
- [x] Adjusted for the short clips: `test_convert` copies the clip to a
      neutral name (the fixture's own "_720p" would be renamed);
      `test_hud_layers` expects >= 3 progress updates (a 2 s clip reports
      ~5; the 10 s one reported > 10).
- [x] Times: full run without release (`run_tests.sh 2`) 2m46s, was ~17 min;
      with `test_data/` hidden 597 passed, 53 skipped in 2m11s (all render
      tests run).

### Phase 4 - parallel (2026-10-06)
- [x] `pytest-xdist` in `requirements.txt` (the dev environment; the app's
      bundled packages come from `pyproject.toml`); `addopts` runs on all
      cores (`-n auto`). `pytest -n0` for a single process / debugger.
- [x] No collisions after Phase 3: three default runs in a row all green
      (53-55 s); without `test_data/` 597 passed, 53 skipped in 45 s.
- [x] `release_test.py`: each test writes to its own
      `test_results/release_test/<test name>` folder instead of one folder
      cleared by a session fixture, so it runs in parallel too.
- [x] Times on the owner's Mac (8 cores):

      | Run | Before Phase 1 | Single process | Parallel |
      |---|---|---|---|
      | 2 Quick (no renders) | - | 1m40s | 28 s |
      | 1 Default (hook) | - | 2m46s | ~54 s |
      | 3 Release only | 5m24s | 5m28s | 3m27s |
      | 4 Everything | 22m11s | ~8m | 5m50s |

      Everything is CPU-bound now: the 4K release renders and the fixture
      renders share the cores, so it is about the release run plus the rest.

### Phase 5 - CI (2026-10-06)
- [x] `.github/workflows/tests.yml`: the default suite on macOS 15, Windows and
      Ubuntu (Python 3.12, Qt off screen, the vendored ffmpeg/exiftool from
      `scripts/fetch_vendored_binaries.py`) on pushes to `main`, `v*` tags and
      by hand. Development branches never reach GitHub, so it first runs when
      `main` is pushed.
- [x] Linux tried locally in Docker first (Ubuntu 24.04 image, no `test_data/`,
      apt's ffmpeg/exiftool since the vendored Linux build is amd64-only and
      Docker Hub pulls hung here). Results in the log below.
- [x] Font difference found: two read-only text boxes (Log Viewer events,
      Overlay Designer waypoint JSON) asked for "Menlo", which only macOS has;
      Windows now gets Consolas and Linux the system monospace font.
- [x] Linux run found 5 failures, all fixed:
      - "Move original" lowercased the moved file's extension (DSC03491.JPG ->
        DSC03491.jpg); hidden on macOS, whose file names ignore case. Fixed in
        `cli_main.py`; the test now lists the folder instead of `.exists()`.
      - Linux drew "Arial" with the system DejaVu Sans (wider) before the bundled
        Liberation Sans; `utils/fonts.py` now takes Liberation first.
        Showed as a 7 px right-align miss in `test_hud_renderer.py`.
      - `test_output_naming.py` assumed a case-insensitive file system.
      - Two Tag Editor tests need exiftool 13 (reads DJI's OriginalFilePath);
        Ubuntu's apt exiftool 12.76 can't. CI uses the vendored 13.59.
- [ ] Windows and macOS runners: first real result when `main` is pushed.

### Phase 6 - coverage (2026-10-06)
- [x] `pytest-cov` (requirements.txt) with `[tool.coverage]` in pyproject.toml:
      `python -m pytest --cov`. `patch = ["subprocess"]` also measures the
      cli_main.py runs of the render tests (without it cli_main.py showed 14%
      instead of 74%). The old widget pages in `uwmedia/pages/` are left out.
      Default run: 67% as first measured -> 78% with subprocesses -> see log.
- [x] Colour: `ffmpeg/color.py` is 94% covered by the render tests.
      `test_color_tuning_backend.py` covers the Color Tuning backend, the
      colour profiles (save, merge, override) and the parameter table.
- [x] Tag Editor: `test_tag_editor.py`, helpers and backend, on copies of the
      fixture media in `tmp_path`.
- [x] `test_ffmpeg_class.py`: encoder per platform, ffprobe helpers, progress
      lines, errors, the command `process_video` builds, one small real encode.
- [x] `cli_main.py`'s `--convert` naming now shares `utils/convert_naming.py`
      with the Convertion page (the table, the name rule, the CLI choices).
      `test_convertion_backend.py` and `test_about_backend.py` added.
- [x] `test_qml_smoke.py`: the app's own wiring (`uwmedia.app.create_engine`)
      loads main.qml off screen with no QML warnings, every `.qml` file
      compiles, and `pyside6-qmllint` reports nothing. qmllint's
      "unqualified" check is off: the pages reach their backends through
      context properties, which it can't see (710 reports, all that).
- [x] Coverage gaps 5 and 7: `test_cli_helpers.py` (`get_unique_path`,
      `print_summary`; the FCPXML export was removed instead), `test_tool_paths.py` (settings
      override vs. search, ffprobe next to ffmpeg, validity checks),
      `test_config.py` (tank mapping: load order, save, rename, remove, broken
      YAML) and the real Windows / Linux (XDG and no-XDG) folders in
      `test_resource_paths.py`, using platformdirs' own Windows / Unix classes.
      `dive_plan_import` was already covered by `test_plan_embed.py`.
- [ ] Re-plan the 3 xfail Subsurface references (owner, in Subsurface):
      `air_long_deco`, `nx32_deco`, `air_multi_deco` were planned 3 minutes
      after another dive. Plan each again with no dive before it (empty
      logbook or a far-off date), paste over `tests/deco_reference/raw/<name>.txt`,
      drop the `known_gap` line, run `python scripts/deco_reference.py convert`.
      Meanwhile `test_planner_matches_the_subsurface_port` checks
      `air_long_deco` and `nx32_deco` against the fresh-tissue port and they
      pass; `air_multi_deco` has two gases, which the port doesn't do yet.

## Log

- 2026-10-06: review done, plan written, Phase 1 done (fast run 1m40s).
- 2026-10-06: Phase 3 done; CLAUDE.md release check now requires `tests/run_tests.sh 4`.
  Complete run after Phase 3: 658 passed, 6 skipped (Windows-only), 3 xfailed in 22m02s.
- 2026-10-06: CONTRIBUTING.md, AGENTS.md and `.githooks/pre-commit` (fast suite before
  each commit; Markdown-only commits skip it) added; hook enabled in the owner's clone.
- 2026-10-06: Phase 2 done; full run without release 2m46s (was ~17 min).
- 2026-10-06: render tests joined the default run (`addopts = -m "not release"`);
  `run_tests.sh` 1 = default (~3 min), 2 = quick without renders (~1.5 min).
- 2026-10-06: Phase 4 done; parallel runs: default ~1 min, everything 5m50s.
- 2026-10-06: Phase 5 + 6: CI workflow, Linux tried in Docker, 7 new test files.
  Coverage of the default run 78% -> 85%. Everything (`run_tests.sh 4`) on macOS:
  739 passed, 6 skipped (Windows-only), 3 xfailed in 5m41s. Linux (Docker): 676 passed,
  53 skipped (no test_data), 2 failed (the exiftool 12.76 Tag Editor pair).
- 2026-10-07: coverage gaps 5 and 7 closed (3 new test files and test_resource_paths.py, 20 new tests); FCPXML
  export removed (owner no longer uses it); default run
  745 passed, 6 skipped (Windows-only), 3 xfailed in 1m06s.
