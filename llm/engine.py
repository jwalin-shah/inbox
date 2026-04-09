"""
Singleton LLM engine — loads Qwen3.5-0.8B once, shared across extraction + autocomplete.

Uses mlx-lm for inference and Outlines for constrained JSON generation.
Model stays hot in memory after first load (~500MB at 4-bit).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

MLX_MODEL = "mlx-community/Qwen3.5-0.8B-MLX-4bit"

_lock = threading.Lock()
_model = None
_tokenizer = None


def _ensure_loaded():
    """Load model + tokenizer once. Thread-safe."""
    global _model, _tokenizer
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        print(f"[llm] Loading {MLX_MODEL}...")
        import mlx_lm

        _model, _tokenizer = mlx_lm.load(MLX_MODEL)
        print("[llm] Model ready.")


def get_outlines_model():
    """Return an Outlines-wrapped model for constrained generation."""
    _ensure_loaded()
    import outlines

    return outlines.models.mlxlm(MLX_MODEL)


def complete(prompt: str, max_tokens: int = 64, temperature: float = 0.7) -> str:
    """Free-form text completion. Used for autocomplete suggestions."""
    _ensure_loaded()
    import mlx_lm
    from mlx_lm.sample_utils import make_sampler

    return mlx_lm.generate(
        _model,
        _tokenizer,
        prompt=prompt,
        max_tokens=max_tokens,
        sampler=make_sampler(temp=temperature),
    )


def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Generate constrained JSON matching a Pydantic schema. Used for extraction."""
    import outlines

    model = get_outlines_model()
    generator = outlines.generate.json(model, schema)
    return generator(prompt)


def is_loaded() -> bool:
    return _model is not None


def warmup():
    """Pre-load the model. Call during server startup to avoid first-request latency."""
    _ensure_loaded()
