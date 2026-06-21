REVISION = "0.0.13"
import multiprocessing
from cli_main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

