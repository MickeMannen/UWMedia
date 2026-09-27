# Building the app

UWMedia is packaged with [Briefcase](https://briefcase.readthedocs.io/) as
two apps sharing one codebase (see `pyproject.toml`):

- **`uwmedia`** - the plain GUI app.
- **`uwmedia-terminal`** - the same GUI plus the `uwmedia` terminal command.

## Build scripts

Each script uses the project's virtual environment automatically:

```bash
./build.sh          # macOS - builds uwmedia (.dmg) and uwmedia-terminal (.pkg)
build.bat           # Windows - builds uwmedia-terminal (.msi)
build.ps1           # Windows, PowerShell
```

They run `briefcase build` and then `briefcase package`; installers end up
under `dist/`.

## Briefcase directly

Leave out `-a` to build every app, or name one:

```bash
briefcase dev -a uwmedia-terminal                 # run from source, GUI or CLI
briefcase build macOS                             # build every app's bundle
briefcase package macOS --adhoc-sign              # package every app
briefcase package macOS -a uwmedia --adhoc-sign   # ...or just the plain GUI app
```

## Why two macOS apps

A normal macOS app lives in `/Applications` and has no terminal command. The
*Terminal* package installs to `/Library` instead and adds the `uwmedia`
command for scripted batch processing. Windows and Linux don't have that
mismatch, so they only ship the CLI + GUI build.

Releases are built and attached to the
[Releases](https://github.com/MickeMannen/UWMedia/releases) page by hand.
