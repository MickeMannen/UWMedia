import sys


def main():
    # No args: launched from Finder/dock, or `uwmedia` with nothing after it -> GUI.
    # Args present: either a real CLI invocation, or the GUI's own "Run" button
    # re-invoking this packaged app's launcher with CLI args (see uwmedia/app.py).
    if len(sys.argv) > 1:
        import multiprocessing

        multiprocessing.freeze_support()
        from cli_main import main as run_cli

        run_cli()
    else:
        from uwmedia.app import main as run_gui

        run_gui().main_loop()


if __name__ == "__main__":
    main()
