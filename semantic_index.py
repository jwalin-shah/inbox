"""Optional local embedding support for the Inbox message index.

Embeddings are deliberately local and best-effort.  The operational search
path remains SQLite FTS5, so a missing model or interrupted embedding build
never makes messages undiscoverable.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

DEFAULT_MODEL_ID = os.environ.get("INBOX_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
MAX_EMBED_TEXT = 4000


def item_embedding_text(item: dict[str, Any]) -> str:
    """Build deterministic, bounded text for one indexed message."""
    parts = [
        str(item.get("subject") or ""),
        str(item.get("sender") or ""),
        str(item.get("snippet") or ""),
        str(item.get("body_text") or ""),
    ]
    return "\n".join(part for part in parts if part).strip()[:MAX_EMBED_TEXT]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LocalTextEmbedder:
    """Lazy local BGE encoder; no message text leaves the machine."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, device: str | None = None) -> None:
        self.model_id = model_id
        self.device_name = device or os.environ.get("INBOX_EMBEDDING_DEVICE", "auto")
        self._tokenizer: Any = None
        self._model: Any = None
        self._device: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("local embedding dependencies are not installed") from exc

        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModel.from_pretrained(self.model_id, local_files_only=True)
        if self.device_name == "auto":
            device_name = "mps" if torch.backends.mps.is_available() else "cpu"
        else:
            device_name = self.device_name
        device = torch.device(device_name)
        model.to(device)
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        self._device = device

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        if not texts:
            return []
        self._load()
        import torch
        import torch.nn.functional as functional

        vectors: list[list[float]] = []
        for start in range(0, len(texts), max(1, batch_size)):
            batch = texts[start : start + max(1, batch_size)]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            with torch.no_grad():
                output = self._model(**inputs).last_hidden_state[:, 0]
                output = functional.normalize(output, p=2, dim=1)
            vectors.extend(output.detach().cpu().float().numpy().tolist())
        return vectors
