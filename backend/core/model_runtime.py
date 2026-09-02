"""Process-wide ownership for heavyweight inference models."""

from __future__ import annotations

from backend.core.diarizer import Diarizer, SpeakerEmbeddingModel
from backend.core.segmentation_refiner import SegmentationModel, SegmentationRefiner
from backend.core.transcriber import Transcriber


class ModelRuntime:
    """Own shared weights while creating session-local stateful facades."""

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        speaker_model: SpeakerEmbeddingModel | None = None,
        segmentation_model: SegmentationModel | None = None,
    ):
        self.transcriber = transcriber or Transcriber()
        self.speaker_model = speaker_model or SpeakerEmbeddingModel()
        self.segmentation_model = segmentation_model or SegmentationModel()

    def create_diarizer(self) -> Diarizer:
        return Diarizer(self.speaker_model)

    def create_segmentation_refiner(self) -> SegmentationRefiner:
        return SegmentationRefiner(self.segmentation_model)

    def load_core_models(self) -> None:
        """Load models required by every transcription session."""
        self.transcriber.load_model()
        self.speaker_model.load_model()


_model_runtime = ModelRuntime()


def get_model_runtime() -> ModelRuntime:
    return _model_runtime
