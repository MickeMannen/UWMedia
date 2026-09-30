import os
import sys

# Set on the hidden-console relaunch (see _relaunch_gui_without_console_window)
# so the second instance knows it is the real GUI process and must not
# relaunch yet again.
_RELAUNCHED_ENV = "UWMEDIA_GUI_RELAUNCHED"


def _windows_console_is_ours_alone() -> bool:
    """True when this process is the only client of its console.

    The packaged Windows build is a console-subsystem exe (Briefcase
    `console_app = true`, so one binary serves both the CLI and the GUI),
    and Windows opens a console window for every launch of such an exe
    before a single line of Python runs. Launched from a terminal, that
    console is the terminal's own and the shell is attached to it as well;
    launched from the Start Menu, Explorer or a shortcut, the console was
    created just for us and nobody else is attached. Only the latter is
    ours to get rid of.
    """
    import ctypes

    pids = (ctypes.c_uint32 * 2)()
    return ctypes.windll.kernel32.GetConsoleProcessList(pids, 2) == 1


def _relaunch_gui_without_console_window() -> bool:
    """Start a second copy of this app for the GUI, with a hidden console.

    A console app cannot cleanly drop the window Windows already gave it:
    FreeConsole() leaves stdio dangling, ShowWindow(GetConsoleWindow()) does
    nothing when Windows Terminal is the console host, and both leave the
    subprocesses we spawn later without a console to inherit. A child
    started with CREATE_NO_WINDOW, on the other hand, gets a console with no
    window at all, for its whole life, and everything it spawns (the CLI
    child that does the processing, ffmpeg, exiftool) inherits that. So:
    spawn that child and return; the window that is already on screen
    closes with this process, a blink after it opened instead of staying
    up behind the GUI for the whole session.

    Returns False when the spawn fails, in which case the caller runs the
    GUI in this process as before (console window and all).
    """
    import subprocess

    exe = os.path.basename(sys.executable).lower()
    if exe.startswith("python"):
        # Source checkout started via a shortcut: keep `python -m uwmedia`.
        cmd = [sys.executable, "-m", "uwmedia"]
    else:
        cmd = [sys.executable]
    env = dict(os.environ)
    env[_RELAUNCHED_ENV] = "1"
    try:
        subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        return False
    return True


def _should_relaunch_for_gui() -> bool:
    if sys.platform != "win32" or os.environ.get(_RELAUNCHED_ENV) == "1":
        return False
    try:
        return _windows_console_is_ours_alone()
    except Exception:
        return False


def main():
    # No args: launched normally -> GUI. Args present: the GUI's own
    # "Start" button (ColorPage._build_command) re-invoking this package's
    # own launcher with CLI args, so processing runs in a separate,
    # killable subprocess instead of blocking the UI thread - mirrors
    # uwmedia/__main__.py's own len(sys.argv) > 1 branch exactly, just
    # rooted in this package instead of the Toga one (this app has no
    # dependency on uwmedia/toga at all, see pyside6_rework.md).
    if len(sys.argv) > 1:
        import multiprocessing

        multiprocessing.freeze_support()
        from cli_main import main as run_cli

        run_cli()
    else:
        if _should_relaunch_for_gui() and _relaunch_gui_without_console_window():
            return
        from uwmedia.app import main as run_app

        run_app()


if __name__ == "__main__":
    main()
