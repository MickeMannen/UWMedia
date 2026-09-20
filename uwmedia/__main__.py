import sys


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
        from uwmedia.app import main as run_app

        run_app()


if __name__ == "__main__":
    main()
