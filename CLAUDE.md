# Rules for the Claude agent

- **Never modify or delete files outside this repo directory.** This includes the user's own media and dive-log folders, the app's real data directory (`~/Library/Application Support/org.christersson.uwmedia/`, and the legacy `~/Library/Application Support/UWMedia/` folder it was migrated from), and anything else on the filesystem outside the repo. Reading files outside the repo (e.g. to locate real test media for live testing) is fine — this rule is about writes and deletes.
  - For live/manual testing that needs real-looking files (test videos, photos, dive logs), use fixtures already under the repo (e.g. `test_data/`) or the scratchpad directory instead of the user's real data folders.
  - If a test genuinely requires touching app state outside the repo (e.g. `settings.json`/`color.yaml` in Application Support), stop and ask first rather than doing it and reverting it afterward.
- Never run `git commit` unless explicitly asked for that specific commit. Editing/staging files and describing changes is fine; leave the commit action itself to the user.

# Shared rules for every coding agent

The rules in `AGENTS.md` (files and data, git, tests, changelog) apply here too; tests and test data are described in `CONTRIBUTING.md`.

@AGENTS.md

# Paths

UWMedia (`uwmedia`, bundle ID `org.christersson.uwmedia`, vendor Christersson) runs on Windows, macOS and Linux.

- Never write logs, config, caches or databases into the install directory, and never hard-code a path.
- Every writable path comes from `utils/resource_paths.py` (`user_config_dir()`, `user_data_dir()`, `user_cache_dir()`, `app_temp_dir()`), which wraps `platformdirs` and handles the Linux `$XDG_*` fallbacks; never build one elsewhere. Create directories (`mkdir -p`) before reading or writing.
- The per-platform folders are listed in `docs/getting-started.md`; user exports go to the system Documents / Pictures folders.

# Changelog and releases

This section is the owner's (maintainer's) workflow. The release steps run only when the owner asks; an agent working for any other contributor skips them.

The owner does the coding, testing and the release builds; Claude keeps the record. Version numbers are the git tags (`v0.7.0`). The "Release Build" GitHub workflow stamps the tag into the build, but the local `build.sh` / `build.ps1` builds read `version` in `pyproject.toml`, so that value is bumped in the release commit and nowhere else.

After every round of work (before the round is called done): add the round's user-facing changes as bullets under `## [Unreleased]` at the top of `CHANGELOG.md`, in the file's existing style (Keep a Changelog: `### Added` / `### Changed` / `### Fixed` subsections; each bullet leads with the page, feature or platform it concerns, e.g. "Overlay Designer:", "Convertion:", "Windows:"): what a user notices and why it matters, one to three lines each, no implementation detail, no bullet for docs-only or internal changes. Create the section or subsection if it is missing.

When the owner says "prepare a release" (or "prepare for release 0.7.1"): invoke the `release` skill (`.claude/skills/release/SKILL.md`) and follow it exactly. "Prepare a release" is the explicit ask for the one release commit that the no-commit rule above requires.
