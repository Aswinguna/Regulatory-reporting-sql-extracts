import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regrep.pipeline import run  # noqa: E402


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory):
    out = tmp_path_factory.mktemp("build")
    con, checks, data_dir = run(out, seed=42)
    truth = json.loads((data_dir / "injected_issues.json").read_text())
    return {"con": con, "checks": checks, "data_dir": data_dir, "truth": truth, "out": out}


@pytest.fixture(scope="session")
def pipeline_fixture_dir(pipeline):
    """Directory holding the generated CSVs, shared by the fault injection tests."""
    return pipeline["data_dir"]
