from backend.config import settings
from backend.core import segmentation_refiner


def test_segmentation_refinement_disabled_when_setting_is_off(monkeypatch):
    monkeypatch.setattr(settings, "segmentation_refine_enabled", False)
    monkeypatch.setattr(settings, "segmentation_refine_allow_cpu", False)
    monkeypatch.setattr(segmentation_refiner.torch.cuda, "is_available", lambda: True)

    assert segmentation_refiner.should_run_segmentation_refinement() is False


def test_segmentation_refinement_skips_cpu_by_default(monkeypatch):
    monkeypatch.setattr(settings, "segmentation_refine_enabled", True)
    monkeypatch.setattr(settings, "segmentation_refine_allow_cpu", False)
    monkeypatch.setattr(segmentation_refiner.torch.cuda, "is_available", lambda: False)

    assert segmentation_refiner.should_run_segmentation_refinement() is False


def test_segmentation_refinement_runs_on_cuda(monkeypatch):
    monkeypatch.setattr(settings, "segmentation_refine_enabled", True)
    monkeypatch.setattr(settings, "segmentation_refine_allow_cpu", False)
    monkeypatch.setattr(segmentation_refiner.torch.cuda, "is_available", lambda: True)

    assert segmentation_refiner.should_run_segmentation_refinement() is True


def test_segmentation_refinement_can_be_forced_on_cpu(monkeypatch):
    monkeypatch.setattr(settings, "segmentation_refine_enabled", True)
    monkeypatch.setattr(settings, "segmentation_refine_allow_cpu", True)
    monkeypatch.setattr(segmentation_refiner.torch.cuda, "is_available", lambda: False)

    assert segmentation_refiner.should_run_segmentation_refinement() is True
