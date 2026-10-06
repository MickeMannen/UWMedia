# Contributing to UWMedia

## Setup

Python 3.10+, with FFmpeg and ExifTool on your `PATH`.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Tests

There are three levels of testing. The first one is the minimum for every
commit.

| When | Command | Time | What runs |
|---|---|---|---|
| Before every commit | `tests/run_tests.sh` (Enter) or `pytest` | ~1 min | Everything except the release run, including render tests on the small media in `tests/fixtures/` |
| A quicker check while working | `tests/run_tests.sh 2` | ~30 s | The same without the render tests |
| Before a release | `tests/run_tests.sh 4` | ~6 min | Everything, including `release_test.py` on the full 4K media |

`tests/run_tests.sh 3` runs only `release_test.py`.

The default suite also runs on GitHub Actions (`.github/workflows/tests.yml`)
on macOS, Windows and Linux for every push to `main` and every release tag.

To see what the tests cover, run `pytest --cov`. It includes the
`cli_main.py` runs the render tests start, and `coverage html` writes a
browsable report to `htmlcov/`.

### Pre-commit hook (recommended)

A hook in `.githooks/` runs the default suite before each commit and stops the
commit if a test fails. Turn it on once per clone:

```bash
git config core.hooksPath .githooks
```

It skips commits that only touch Markdown files. To commit anyway in an
emergency, use `git commit --no-verify`, then fix the tests in the next
commit.

### Test data

- `test_data/` holds the owner's private media and dive logs. It is not in
  git, so on a fresh clone the tests that need it skip themselves rather
  than fail. To use a copy stored somewhere else, set
  `UWMEDIA_TEST_DATA=/path/to/test_data`.
- `tests/fixtures/` holds the small media files that are in git; its
  `README.md` lists each file and its review. The render tests use them,
  with synthetic logs from `write_synthetic_log()` / the `synthetic_logs`
  fixture in `tests/conftest.py`.
- **Dive logs are never committed.** FIT, UDDF, SSRF, Shearwater XML/CSV and
  other dive-profile files contain device serial numbers and personal IDs.
  A test that needs a log builds a synthetic one at run time with the app's
  own writers (`parsers/fit_writer.py`, the UDDF and Subsurface writers).
- **Photos and videos go into git only after the owner has reviewed them**,
  including their metadata (EXIF/XMP can hold camera serial numbers, names
  and GPS).

### Writing tests

- Write output to pytest's `tmp_path`, never into the repo or `test_data/`.
- Use the helpers in `tests/conftest.py`: `TEST_DATA`, `RELEASE_MEDIA` and
  `LOGS_DIR` for paths, and `run_cli(...)` to run `cli_main.py` with the
  current interpreter from the repo root.
- Markers (registered in `pyproject.toml`):
  - `render`: renders the fixture media through `cli_main.py` (slower).
  - `release`: `release_test.py`.
  - `requires_media`: reads `test_data/`; skipped when it is missing.
  - `windows`: Windows-only checks.
- Never write to the real app folders (Application Support, `~/.config`,
  caches). `tests/conftest.py` already points them at temporary folders.
- `tests/test_qml_smoke.py` loads every QML page off screen and runs
  `pyside6-qmllint`; a QML warning fails it, so run it after changing a page.
- Tests run in parallel on all CPU cores (pytest-xdist, set in
  `pyproject.toml`), so a test must not depend on another test or share a
  fixed file path with one. Use `pytest -n0` to run in a single process,
  e.g. under a debugger.

## Code rules

- Every writable path comes from `utils/resource_paths.py`
  (`user_config_dir()`, `user_data_dir()`, `user_cache_dir()`,
  `app_temp_dir()`); never build one elsewhere. They resolve to the
  platform's standard folders (macOS Application Support / Caches, Windows
  `%APPDATA%` / `%LOCALAPPDATA%`, Linux XDG), never the install folder.
- User-facing changes get a bullet under `## [Unreleased]` in
  `CHANGELOG.md` (Keep a Changelog style: `### Added` / `### Changed` /
  `### Fixed`; each bullet starts with the page or feature it concerns).

## Branches

Development happens on local branches and the self-hosted Gitea. Only
`main` and release tags are pushed to GitHub.
