"""The repository layout HACS and hassfest expect."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "mariadb_export"


def test_hacs_repository_layout() -> None:
    """One integration lives under custom_components, with HACS metadata."""

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))

    assert hacs["name"] == "MariaDB Export"
    assert manifest["domain"] == "mariadb_export"
    assert manifest["config_flow"] is True
    assert manifest["version"]
    assert manifest["documentation"].startswith("https://")
    assert manifest["issue_tracker"].startswith("https://")
    assert manifest["codeowners"] == ["@Daniel-Shoji"]
    assert "PyMySQL" in "".join(manifest["requirements"])
    assert (COMPONENT / "__init__.py").is_file()
    assert (COMPONENT / "config_flow.py").is_file()
    assert services["export"]["fields"]["dataset"]["required"] is True
    assert strings["entity"]["sensor"]["last_export"]["state"]["success"] == "Success"
    names = {
        path.name
        for path in (ROOT / "custom_components").iterdir()
        if path.name != "__pycache__"
    }
    assert names == {"mariadb_export"}
