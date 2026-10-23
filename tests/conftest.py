import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("DOCDRIFT_MOCK", "1")


@pytest.fixture
def demo_repo(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["bash", str(ROOT / "demo" / "setup_demo.sh"), str(repo)], check=True, capture_output=True)
    subprocess.run(["bash", str(ROOT / "demo" / "make_change.sh"), str(repo)], check=True, capture_output=True)
    return repo
