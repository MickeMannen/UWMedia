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
| Before every commit | `tests/run_tests.sh` (Enter) or `pytest` | ~1.5 min | Everything except media renders and the release run |
| When you change rendering, colour, overlays or the CLI | `tests/run_tests.sh 2` | ~17 min | Fast suite + media render tests |
| Before a release | `tests/run_tests.sh 4` | ~22 min | Everything, including `release_test.py` on the full 4K media |

`tests/run_tests.sh 3` runs only `release_test.py`.

### Pre-commit hook (recommended)

A hook in `.githooks/` runs the fast suite before each commit and stops the
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
- `tests/fixtures/` holds the small media files that are in git (see
  `testing_plan.md`, "Fixture layout").
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
  - `render`: renders real media through `cli_main.py` (slow).
  - `release`: `release_test.py`.
  - `requires_media`: reads `test_data/`; skipped when it is missing.
  - `windows`: Windows-only checks.
- Never write to the real app folders (Application Support, `~/.config`,
  caches). `tests/conftest.py` already points them at temporary folders.

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
