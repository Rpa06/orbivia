import math
import os
from typing import Any

from huggingface_hub import snapshot_download
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = "Hrishikesh4/mental-health-classifier-longformer"
MODEL_REVISION = "54edff7f513b60314a4171c848ebe33c2850039a"
MAX_INPUT_TOKENS = 4096
MODEL_FILES = [
    "*.json",
    "model.safetensors",
    "merges.txt",
    "vocab.json",
]


class ClassificationError(RuntimeError):
    pass


class MentalHealthTextClassifier:
    def __init__(self) -> None:
        self._model_id = os.environ.get("MENTAL_HEALTH_MODEL", MODEL_ID)
        self._revision = os.environ.get("MENTAL_HEALTH_MODEL_REVISION", MODEL_REVISION)
        self._cache_dir = os.environ.get("MENTAL_HEALTH_MODEL_PATH", "/models/longformer")
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None

    def load_model(self) -> None:
        import torch

        torch.set_num_threads(int(os.environ.get("WHISPER_CPU_THREADS", "2")))
        model_path = snapshot_download(
            repo_id=self._model_id,
            revision=self._revision,
            cache_dir=self._cache_dir,
            allow_patterns=MODEL_FILES,
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_path,
            local_files_only=True,
            use_safetensors=True,
        )
        if model.config.problem_type != "multi_label_classification":
            raise RuntimeError("The configured text model is not multi-label")
        if model.config.num_labels != 4:
            raise RuntimeError("The configured text model must return four labels")

        model.eval()
        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model

    def classify(self, text: str) -> dict[str, Any]:
        if self._model is None or self._tokenizer is None or self._torch is None:
            raise RuntimeError("Text classifier was not initialized")
        if not text.strip():
            raise ClassificationError("Cannot classify an empty transcript")

        try:
            full_input_ids = self._tokenizer(
                text,
                add_special_tokens=True,
                truncation=False,
            )["input_ids"]
            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=MAX_INPUT_TOKENS,
            )
            with self._torch.inference_mode():
                logits = self._model(**inputs).logits[0]
                probabilities = self._torch.sigmoid(logits).tolist()
        except (RuntimeError, ValueError, OSError, TypeError, KeyError) as error:
            raise ClassificationError("Text classification failed") from error

        id2label = self._model.config.id2label
        scores: dict[str, float] = {}
        for index, probability in enumerate(probabilities):
            label = id2label.get(index, id2label.get(str(index), f"LABEL_{index}"))
            score = float(probability)
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ClassificationError("Text model returned an invalid score")
            scores[label] = score

        return {
            "model": self._model_id,
            "revision": self._revision,
            "problem_type": "multi_label_classification",
            "input_tokens": len(inputs["input_ids"][0]),
            "input_truncated": len(full_input_ids) > MAX_INPUT_TOKENS,
            "scores": scores,
        }
