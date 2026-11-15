"""Entry point of the packaged desktop app (PyInstaller): ``fit-push.exe``.

Same options as ``python -m app``; opens the browser by default.
"""

import multiprocessing
import sys

from app.__main__ import desktop_main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(desktop_main())
