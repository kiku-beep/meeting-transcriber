from pathlib import Path


def test_start_server_has_no_default_shared_auth_token():
    script = Path("scripts/start_server.ps1").read_text(encoding="utf-8")

    assert "monochrome2026" not in script
    assert '[string]$AuthToken = ""' in script
