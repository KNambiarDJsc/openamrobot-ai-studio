import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ros-adapter"))  # adapter is not pip-installed (it runs in the ROS env)

from oar_contracts import Snapshot  # noqa: E402

FIXTURES = ROOT / "fixtures"
FIXTURE_IDS = sorted(p.stem for p in FIXTURES.glob("*.json"))


def load_fixture(fid: str):
    d = json.loads((FIXTURES / f"{fid}.json").read_text(encoding="utf-8"))
    return Snapshot.model_validate(d["snapshot"]), datetime.fromisoformat(d["fixture"]["evaluate_at"].replace("Z", "+00:00")), d


@pytest.fixture
def fixture_loader():
    return load_fixture
