"""Train a LoRA adapter for kotoba-whisper from corrected review samples."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_BASE_MODEL = "kotoba-tech/kotoba-whisper-v2.0"
REQUIRED_PACKAGES = [
    "torch",
    "transformers",
    "datasets",
    "accelerate",
    "peft",
]


@dataclass(frozen=True)
class TrainingPaths:
    review_dir: Path
    train_jsonl: Path
    validation_jsonl: Path
    output_dir: Path
    base_model: str


def resolve_training_paths(
    review_dir: Path,
    train_jsonl: Path | None = None,
    validation_jsonl: Path | None = None,
    output_dir: Path | None = None,
    base_model: str = DEFAULT_BASE_MODEL,
) -> TrainingPaths:
    review_dir = Path(review_dir)
    return TrainingPaths(
        review_dir=review_dir,
        train_jsonl=train_jsonl or (review_dir / "train.jsonl"),
        validation_jsonl=validation_jsonl or (review_dir / "validation.jsonl"),
        output_dir=output_dir or (review_dir / "lora_kotoba_v2"),
        base_model=base_model,
    )


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_manifest_records(path: Path, review_dir: Path) -> list[dict]:
    path = Path(path)
    review_dir = Path(review_dir)
    records = _load_jsonl(path)
    if not records:
        raise ValueError(f"{path} has no records")

    result = []
    for index, record in enumerate(records, start=1):
        audio_filepath = str(record.get("audio_filepath") or "").strip()
        text = str(record.get("text") or "").strip()
        if not audio_filepath:
            raise ValueError(f"{path} record {index}: audio_filepath is blank")
        if not text:
            raise ValueError(f"{path} record {index}: text is blank")
        audio_path = review_dir / audio_filepath
        if not audio_path.exists():
            raise ValueError(f"{path} record {index}: audio file not found: {audio_filepath}")
        info = sf.info(str(audio_path))
        result.append(
            {
                "audio_path": str(audio_path),
                "text": text,
                "duration_s": float(record.get("duration_s") or info.duration),
                "sample_rate": int(info.samplerate),
            }
        )
    return result


def check_training_environment() -> dict:
    missing = [
        package
        for package in REQUIRED_PACKAGES
        if importlib.util.find_spec(package) is None
    ]
    cuda_available = False
    torch_version = None
    if "torch" not in missing:
        import torch

        torch_version = torch.__version__
        cuda_available = bool(torch.cuda.is_available())

    return {
        "ok": not missing,
        "missing_packages": missing,
        "torch_version": torch_version,
        "cuda_available": cuda_available,
    }


def _lazy_import_training_deps():
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        WhisperForConditionalGeneration,
        WhisperProcessor,
    )

    return {
        "Dataset": Dataset,
        "LoraConfig": LoraConfig,
        "Seq2SeqTrainer": Seq2SeqTrainer,
        "Seq2SeqTrainingArguments": Seq2SeqTrainingArguments,
        "WhisperForConditionalGeneration": WhisperForConditionalGeneration,
        "WhisperProcessor": WhisperProcessor,
        "get_peft_model": get_peft_model,
    }


def _prepare_dataset(records: list[dict], processor):
    import numpy as np
    from datasets import Dataset

    def preprocess(record):
        audio, sample_rate = sf.read(record["audio_path"], dtype="float32")
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        inputs = processor.feature_extractor(
            audio,
            sampling_rate=sample_rate,
            return_tensors="pt",
        )
        labels = processor.tokenizer(record["text"]).input_ids
        return {
            "input_features": inputs.input_features[0].numpy(),
            "labels": labels,
        }

    return Dataset.from_list(records).map(
        preprocess,
        remove_columns=list(records[0].keys()),
    )


class DataCollatorSpeechSeq2SeqWithPadding:
    def __init__(self, processor):
        self.processor = processor

    def __call__(self, features):
        input_features = [
            {"input_features": feature["input_features"]}
            for feature in features
        ]
        batch = self.processor.feature_extractor.pad(input_features, return_tensors="pt")

        label_features = [{"input_ids": feature["labels"]} for feature in features]
        labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch.attention_mask.ne(1),
            -100,
        )
        batch["labels"] = labels
        return batch


def train_lora(
    paths: TrainingPaths,
    epochs: float = 10.0,
    learning_rate: float = 1e-4,
    per_device_batch_size: int = 1,
    gradient_accumulation_steps: int = 8,
    lora_rank: int = 16,
    lora_alpha: int = 32,
) -> dict:
    env = check_training_environment()
    if not env["ok"]:
        raise RuntimeError(
            "Missing training packages: "
            + ", ".join(env["missing_packages"])
            + ". Install requirements-lora.txt first."
        )

    deps = _lazy_import_training_deps()
    train_records = load_manifest_records(paths.train_jsonl, paths.review_dir)
    eval_records = load_manifest_records(paths.validation_jsonl, paths.review_dir)

    processor = deps["WhisperProcessor"].from_pretrained(
        paths.base_model,
        language="Japanese",
        task="transcribe",
    )
    model = deps["WhisperForConditionalGeneration"].from_pretrained(paths.base_model)
    model.config.forced_decoder_ids = None
    model.config.suppress_tokens = []
    model.config.use_cache = False

    lora_config = deps["LoraConfig"](
        r=lora_rank,
        lora_alpha=lora_alpha,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
    )
    model = deps["get_peft_model"](model, lora_config)

    train_dataset = _prepare_dataset(train_records, processor)
    eval_dataset = _prepare_dataset(eval_records, processor)
    data_collator = DataCollatorSpeechSeq2SeqWithPadding(processor)

    training_args = deps["Seq2SeqTrainingArguments"](
        output_dir=str(paths.output_dir),
        per_device_train_batch_size=per_device_batch_size,
        per_device_eval_batch_size=per_device_batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        warmup_steps=10,
        num_train_epochs=epochs,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=3,
        predict_with_generate=False,
        fp16=env["cuda_available"],
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = deps["Seq2SeqTrainer"](
        args=training_args,
        model=model,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        tokenizer=processor.feature_extractor,
    )
    train_result = trainer.train()
    trainer.save_model(str(paths.output_dir))
    processor.save_pretrained(str(paths.output_dir))

    summary = {
        "base_model": paths.base_model,
        "output_dir": str(paths.output_dir),
        "train_rows": len(train_records),
        "validation_rows": len(eval_records),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "per_device_batch_size": per_device_batch_size,
        "gradient_accumulation_steps": gradient_accumulation_steps,
        "lora_rank": lora_rank,
        "lora_alpha": lora_alpha,
        "metrics": train_result.metrics,
    }
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    (paths.output_dir / "training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _default_review_dir() -> Path:
    return PROJECT_ROOT / "training_data" / "review_samples_recent"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a PEFT LoRA adapter for kotoba-whisper-v2.0.",
    )
    parser.add_argument("--review-dir", type=Path, default=_default_review_dir())
    parser.add_argument("--train-jsonl", type=Path, default=None)
    parser.add_argument("--validation-jsonl", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--epochs", type=float, default=10.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--per-device-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--check-env", action="store_true")
    args = parser.parse_args()

    if args.check_env:
        print(json.dumps(check_training_environment(), ensure_ascii=False, indent=2))
        return

    paths = resolve_training_paths(
        review_dir=args.review_dir,
        train_jsonl=args.train_jsonl,
        validation_jsonl=args.validation_jsonl,
        output_dir=args.output_dir,
        base_model=args.base_model,
    )
    summary = train_lora(
        paths=paths,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        lora_rank=args.lora_rank,
        lora_alpha=args.lora_alpha,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
