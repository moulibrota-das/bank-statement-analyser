import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bsi.api.deps import settings_dep
from bsi.api.main import create_app
from bsi.config import Settings
from bsi.pipeline import analyze_file
from tests.conftest import sample_file

WEB = Path(__file__).resolve().parents[2] / "web"


def client():
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: Settings(mock=True)
    return TestClient(app)


def test_root_serves_the_designed_ui_and_assets():
    c = client()
    r = c.get("/")
    assert r.status_code == 200 and "Statement Analyser" in r.text
    for asset in ("styles.css", "model.js", "app.js"):
        assert c.get(f"/{asset}").status_code == 200


def test_api_routes_are_not_shadowed_by_the_static_mount():
    c = client()
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/health").json()["max_upload_mb"] == 10
    assert c.get("/docs").status_code == 200 and c.get("/samples").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", ["nimbus_a_2024_q1", "orchid_b_2024_07", "velocity_c_2024_10"])
def test_view_model_logic_under_node(tmp_path, name):
    report = tmp_path / "report.json"
    report.write_text(analyze_file(sample_file(name)).model_dump_json())
    proc = subprocess.run(["node", "--test", str(Path(__file__).with_name("model.test.mjs"))],
                          env={"REPORT_JSON": str(report), "PATH": __import__("os").environ["PATH"]},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_app_js_parses():
    assert subprocess.run(["node", "--check", str(WEB / "app.js")]).returncode == 0
    assert json.loads(json.dumps({"ok": True}))
