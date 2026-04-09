"""
Shared Whisper configuration for ambient + dictation modes.
"""

from pathlib import Path

# MLX Whisper for chunk-based ambient transcription
MLX_WHISPER_MODEL = "mlx-community/whisper-base.en-mlx"

# whisper-stream C++ binary for real-time dictation
WHISPER_STREAM_BIN = "/opt/homebrew/bin/whisper-stream"
WHISPER_STREAM_MODEL = (
    "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-base.en-q8_0.bin"
)

# Audio settings
SAMPLE_RATE = 16000
CHUNK_SECS = 5  # ambient: transcribe every N seconds
SILENCE_RMS_THRESHOLD = 0.01  # skip chunks below this RMS

# Vocabulary prompt — biases whisper toward these technical terms
VOCAB_PROMPT = (
    "Claude Code, mlx-lm, mlx-whisper, Outlines, Qwen, Textual, "
    "Ghostty, Raycast, AeroSpace, sketchybar, FastAPI, inbox"
)


def whisper_stream_available() -> bool:
    return Path(WHISPER_STREAM_BIN).exists() and Path(WHISPER_STREAM_MODEL).exists()
