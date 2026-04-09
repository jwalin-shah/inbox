"""
Ambient background transcription service.
Runs in a background thread, captures audio chunks, transcribes with mlx-whisper,
extracts structured notes, and stores them via a callback.

Ported from ~/projects/ambient/transcribe.py — now integrated into the inbox server.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from audio.whisper import (
    CHUNK_SECS,
    MLX_WHISPER_MODEL,
    SAMPLE_RATE,
    SILENCE_RMS_THRESHOLD,
)

MIN_CHUNK_WORDS = 10
FLUSH_INTERVAL = 60  # seconds between extraction passes


class AmbientService:
    """Background ambient transcription service."""

    def __init__(self, on_note: Callable[[str, str | None], None]):
        """
        Args:
            on_note: callback(raw_transcript, extracted_summary) called when a note is ready.
                     extracted_summary may be None if extraction finds nothing useful.
        """
        self._on_note = on_note
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._flush_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._capture_thread.start()
        self._flush_thread.start()
        print("[ambient] Started listening.")

    def stop(self):
        if not self._running:
            return
        self._running = False
        # Process remaining buffer
        self._process_buffer()
        print("[ambient] Stopped.")

    def _capture_loop(self):
        import mlx_whisper
        import sounddevice as sd

        while self._running:
            try:
                audio = sd.rec(
                    int(CHUNK_SECS * SAMPLE_RATE),
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                )
                sd.wait()

                if not self._running:
                    break

                audio_flat = audio.flatten()
                rms = float(np.sqrt(np.mean(audio_flat**2)))
                if rms < SILENCE_RMS_THRESHOLD:
                    continue

                result = mlx_whisper.transcribe(
                    audio_flat, path_or_hf_repo=MLX_WHISPER_MODEL, language="en"
                )
                text = result.get("text", "").strip()
                if text:
                    with self._buffer_lock:
                        self._buffer.append(text)

            except Exception as e:
                print(f"[ambient] Capture error: {e}")
                time.sleep(1)

    def _flush_loop(self):
        while self._running:
            time.sleep(FLUSH_INTERVAL)
            if self._running:
                self._process_buffer()

    def _process_buffer(self):
        with self._buffer_lock:
            if not self._buffer:
                return
            chunk = " ".join(self._buffer)
            self._buffer.clear()

        if len(chunk.split()) < MIN_CHUNK_WORDS:
            return

        # Run extraction in a try/except so audio capture isn't affected
        summary = None
        try:
            from llm.extract import extract_summary

            summary = extract_summary(chunk)
        except Exception as e:
            print(f"[ambient] Extraction error: {e}")

        self._on_note(chunk, summary)
