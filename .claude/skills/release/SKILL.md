---
name: release
description: Prepare a UWMedia release - changelog section, version bump, release commit, tag, push and GitHub release. Use when the owner says "prepare a release" or "prepare for release <version>".
model: sonnet
---

# Prepare a release

This is the owner's (maintainer's) workflow; skip it for any other contributor. Version numbers are the git tags (`v0.7.0`). The "Release Build" GitHub workflow stamps the tag into the build, but the local `build.sh` / `build.ps1` builds read `version` in `pyproject.toml`, so that value is bumped in the release commit and nowhere else.

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
