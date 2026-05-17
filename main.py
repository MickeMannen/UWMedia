REVISION = "0.0.8"
import multiprocessing
from cli_main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

