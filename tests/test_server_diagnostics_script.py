from pathlib import Path
import subprocess


def test_diagnose_server_script_checks_required_prerequisites():
    script = Path("scripts/diagnose_server.ps1").read_text(encoding="utf-8")

    assert "nvidia-smi" in script
    assert "tailscale" in script
    assert "tailscale ip -4" in script
    assert ".venv\\Scripts\\python.exe" in script
    assert "torch.cuda.is_available" in script
    assert "ctranslate2" in script
    assert "HF_TOKEN" in script
    assert "DEPLOYMENT_MODE" in script
    assert "Invoke-WebRequest" in script


def test_diagnose_server_accepts_bind_host_port_and_health_check_options():
    script = Path("scripts/diagnose_server.ps1").read_text(encoding="utf-8")

    assert '[string]$BindHost = ""' in script
    assert "[int]$Port = 8000" in script
    assert "[switch]$SkipHealth" in script
    assert "http://$BindHost`:$Port/api/health" in script
    assert "http://$BindHost`:$Port/api/health/gpu" in script


def test_diagnose_server_script_is_valid_powershell():
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "$null = [scriptblock]::Create((Get-Content -Raw scripts/diagnose_server.ps1))",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
