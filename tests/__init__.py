"""Test package — points the app at a throwaway downloads folder and
settings file *before* anything imports ytarabic.config, so tests never
touch your real library.

Run:  python -m unittest discover -s tests -t .
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="ytarabic-tests-"))
atexit.register(shutil.rmtree, TEST_ROOT, ignore_errors=True)
os.environ["YTARABIC_DOWNLOAD_DIR"] = str(TEST_ROOT / "downloads")
os.environ["YTARABIC_SETTINGS_FILE"] = str(TEST_ROOT / "settings.json")
