from pathlib import Path


def test_start_server_has_no_default_shared_auth_token():
    script = Path("scripts/start_server.ps1").read_text(encoding="utf-8")

    assert "monochrome2026" not in script
    assert '[string]$AuthToken = ""' in script


def test_start_server_does_not_hardcode_tailscale_ip():
    script = Path("scripts/start_server.ps1").read_text(encoding="utf-8")

    assert "100.116.182.31" not in script
    assert '[string]$BindHost = ""' in script
    assert "[int]$Port = 8000" in script
    assert "tailscale ip -4" in script
    assert "--host $BindHost" in script
    assert "--port $Port" in script
