# Rules for the Claude agent

- **Never modify or delete files outside this repo directory.** This includes the user's own media and dive-log folders, the app's real data directory (`~/Library/Application Support/org.christersson.uwmedia/`, and the legacy `~/Library/Application Support/UWMedia/` folder it was migrated from), and anything else on the filesystem outside the repo. Reading files outside the repo (e.g. to locate real test media for live testing) is fine — this rule is about writes and deletes.
  - For live/manual testing that needs real-looking files (test videos, photos, dive logs), use fixtures already under the repo (e.g. `test_data/`) or the scratchpad directory instead of the user's real data folders.
  - If a test genuinely requires touching app state outside the repo (e.g. `settings.json`/`color.yaml` in Application Support), stop and ask first rather than doing it and reverting it afterward.
- Never run `git commit` unless explicitly asked for that specific commit. Editing/staging files and describing changes is fine; leave the commit action itself to the user.

# Shared rules for every coding agent

The rules in `AGENTS.md` (files and data, git, tests, changelog) apply here too; tests and test data are described in `CONTRIBUTING.md`.

@AGENTS.md

# Desktop File System & Path Architecture Guidelines

You are developing **UWMedia** (`uwmedia`), a cross-platform desktop application running on Windows, macOS, and Linux.

## 1. Identity & Namespaces
- **Domain:** christersson.org
- **Vendor / Organization Name:** Christersson
- **Application Slug:** uwmedia
- **Bundle / App ID (Reverse-DNS):** org.christersson.uwmedia

## 2. Installation Paths
Static binaries and read-only assets must remain isolated from user-generated content:
- **Windows (Per-User Default):** `%LOCALAPPDATA%\Programs\uwmedia\`
- **Windows (Machine-Wide Admin):** `%ProgramFiles%\Christersson\uwmedia\`
- **macOS:** `/Applications/UWMedia.app` (or `~/Applications/UWMedia.app`)
- **Linux:** `~/.local/bin/uwmedia` (Desktop entry: `~/.local/share/applications/org.christersson.uwmedia.desktop`) or Flatpak `org.christersson.uwmedia`

## 3. Runtime Data & Storage Separation
Never write runtime logs, config, or databases into the install directory:
- **Config:** Windows: `%APPDATA%\Christersson\UWMedia\` | macOS: `~/Library/Application Support/org.christersson.uwmedia/` | Linux: `$XDG_CONFIG_HOME/uwmedia/` (default: `~/.config/uwmedia/`)
- **Local Data / DB:** Windows: `%LOCALAPPDATA%\Christersson\UWMedia\` | macOS: `~/Library/Application Support/org.christersson.uwmedia/` | Linux: `$XDG_DATA_HOME/uwmedia/` (default: `~/.local/share/uwmedia/`)
- **Cache / Temp:** Windows: `%LOCALAPPDATA%\Christersson\UWMedia\Cache\` | macOS: `~/Library/Caches/org.christersson.uwmedia/` | Linux: `$XDG_CACHE_HOME/uwmedia/` (default: `~/.cache/uwmedia/`)
- **User Exports:** System Documents/Pictures directory.

## 4. Implementation Rules
1. Never hardcode paths using raw strings. Always resolve paths dynamically via standard platform APIs (e.g., Rust's `directories`, Python's `platformdirs`, Qt's `QStandardPaths`, or Electron's `app.getPath()`).
2. Verify and create directories recursively (`mkdir -p`) before read/write operations.
3. Handle Linux `$XDG_*` fallbacks properly.
4. In this codebase every writable path comes from `utils/resource_paths.py` (`user_config_dir()`, `user_data_dir()`, `user_cache_dir()`, `app_temp_dir()`), which wraps `platformdirs`; never build one elsewhere.

# Changelog and releases

This section is the owner's (maintainer's) workflow. The release steps below run only when the owner asks; an agent working for any other contributor skips them.

The owner does the coding, testing and the release builds; Claude keeps the record. Version numbers are the git tags (`v0.7.0`). The "Release Build" GitHub workflow stamps the tag into the build, but the local `build.sh` / `build.ps1` builds read `version` in `pyproject.toml`, so that value is bumped in the release commit and nowhere else.

After every round of work (before the round is called done): add the round's user-facing changes as bullets under `## [Unreleased]` at the top of `CHANGELOG.md`, in the file's existing style (Keep a Changelog: `### Added` / `### Changed` / `### Fixed` subsections; each bullet leads with the page, feature or platform it concerns, e.g. "Overlay Designer:", "Convertion:", "Windows:"): what a user notices and why it matters, one to three lines each, no implementation detail, no bullet for docs-only or internal changes. Create the section or subsection if it is missing.

When the owner says "prepare a release" (or "prepare for release 0.7.1"): do these steps, on `main`, and stop before anything the owner did not ask for.

1. Pick the version: the one the owner named, otherwise the next patch number after the newest tag (`git tag --sort=-v:refname | head -1`). Say which one you chose.
2. Rename `## [Unreleased]` in `CHANGELOG.md` to `## [<version>] - <today, YYYY-MM-DD>`, set `version = "<version>"` in `pyproject.toml`, and tidy the bullets so they read as release notes; do not add things that are not in the tree. Show the section to the owner before going on.
3. Commit those two files on `main` with the message `Release <version>`, then tag it `v<version>` and push branch and tag to both remotes: `git push github main v<version>` and `git push gitea main v<version>`. "Prepare a release" is the explicit ask for this one commit that the no-commit rule above requires.
4. Create the GitHub release with the tag as the release. The notes are a brief overview, not the changelog: one sentence saying what the release is about, then at most 8 bullets for the changes a user would notice most, most noticeable first. Each bullet is one short line (about 12 words, no second clause), and one bullet covers a whole feature or page rather than each detail of it. Use no **Added** / **Changed** / **Fixed** headings, sub-bullets, numbers, element keys or CLI flags; leave smaller changes to the changelog. End with a link to the full section: `Full notes: https://github.com/MickeMannen/UWMedia/blob/v<version>/CHANGELOG.md`. About 12 lines in all. Write the notes file in the session scratchpad, not the repo:
   ```
   gh release create v<version> --title "UWMedia <version>" --notes-file <scratchpad>/notes.md --repo MickeMannen/UWMedia
   ```
5. Report the release URL and stop. The owner then runs the "Release Build" workflow from the tag on GitHub (Actions, "Run workflow", "Use workflow from" set to the tag, "Create/update the GitHub Release" checked), which builds the installers and attaches them to the release without touching the notes; Claude does not trigger that workflow.

Tagging and creating the release are public and hard to undo, so if the tree is dirty, the complete test run (`tests/run_tests.sh 4`, "Everything" - the default run is not enough) has not passed this session, or the version already exists as a tag, say so and stop instead of proceeding.
