# Instructions for AI coding agents

These rules apply to any coding agent working in this repo (Claude Code,
Codex, Cursor, Gemini, Antigravity and others).

## Files and data
- Never write or delete files outside this repo folder. That includes the
  user's media folders and the app's real data folders (macOS:
  `~/Library/Application Support/org.christersson.uwmedia/`). For test files
  use the repo's fixtures or a temporary folder.
- Every writable path in the app comes from `utils/resource_paths.py`
  (`user_config_dir()`, `user_data_dir()`, `user_cache_dir()`,
  `app_temp_dir()`). Never build one elsewhere or hard-code one.

## Git
- Never commit unless the owner asks for that specific commit.
- Never add dive-log files (FIT, UDDF, SSRF, Shearwater XML/CSV) to git.
  They contain device serial numbers and personal IDs.
- Never add photos or videos to git without the owner's review of each
  file and its metadata.
- Only `main` and release tags go to GitHub; development branches don't.

## Tests
Follow `CONTRIBUTING.md`:
- Run the default suite (`tests/run_tests.sh 1`) before saying work is done,
  and `tests/run_tests.sh 4` before a release.
- Always pass `tests/run_tests.sh` a choice (1-5) when there is no
  terminal.
- Report failures as they are. Don't skip or weaken tests to make them pass.
- `testing_plan.md` is the working doc for the test suite. Tick items off
  there as they are done.

## Changelog
User-facing changes get a bullet under `## [Unreleased]` in `CHANGELOG.md`.
Follow the existing style there.
