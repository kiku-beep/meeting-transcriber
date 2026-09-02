from backend.config import Settings
from backend.core.audio_capture import AudioDevice, select_preferred_loopbacks


def make_device(
    index: int,
    name: str,
    *,
    host_api: str = "Windows WASAPI",
    is_loopback: bool = True,
) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        host_api=host_api,
        max_input_channels=2,
        default_sample_rate=48000.0,
        is_loopback=is_loopback,
    )


def test_preferred_loopback_patterns_parse_names(monkeypatch):
    monkeypatch.setenv(
        "LOOPBACK_DEVICE_PATTERNS",
        "INZONE H3, Anker PowerConf S330",
    )

    config = Settings(_env_file=None)

    assert config.preferred_loopback_patterns == (
        "INZONE H3",
        "Anker PowerConf S330",
    )


def test_empty_preferred_loopback_patterns_restore_default_only(monkeypatch):
    monkeypatch.setenv("LOOPBACK_DEVICE_PATTERNS", "")

    config = Settings(_env_file=None)

    assert config.preferred_loopback_patterns == ()


def test_select_preferred_loopbacks_matches_names_in_pattern_order():
    devices = [
        make_device(29, "スピーカー (2- Anker PowerConf S330) [Loopback]"),
        make_device(25, "スピーカー (2- INZONE H3) [Loopback]"),
    ]

    selected = select_preferred_loopbacks(
        devices,
        ("inzone h3", "ANKER POWERCONF S330"),
    )

    assert [device.index for device in selected] == [25, 29]


def test_select_preferred_loopbacks_ignores_non_wasapi_and_inputs():
    devices = [
        make_device(1, "マイク (INZONE H3)", is_loopback=False),
        make_device(2, "INZONE H3 [Loopback]", host_api="MME"),
        make_device(25, "INZONE H3 [Loopback]"),
    ]

    selected = select_preferred_loopbacks(devices, ("INZONE H3",))

    assert [device.index for device in selected] == [25]


def test_select_preferred_loopbacks_deduplicates_device_indices():
    devices = [make_device(25, "INZONE H3 Anker PowerConf S330 [Loopback]")]

    selected = select_preferred_loopbacks(
        devices,
        ("INZONE H3", "Anker PowerConf S330"),
    )

    assert [device.index for device in selected] == [25]


def test_select_preferred_loopbacks_returns_empty_for_empty_patterns():
    devices = [make_device(25, "INZONE H3 [Loopback]")]

    assert select_preferred_loopbacks(devices, ()) == []
