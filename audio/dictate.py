"""
Real-time dictation — streams whisper-stream output and types at cursor position.
Runs as a background service, can be toggled on/off.

Ported from ~/projects/ambient/dictate.py — now integrated into the inbox server.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time

from audio.whisper import (
    VOCAB_PROMPT,
    WHISPER_STREAM_BIN,
    WHISPER_STREAM_MODEL,
    whisper_stream_available,
)


def _type_text(text: str):
    """Inject text at current cursor position via macOS CGEvent."""
    import Quartz

    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for char in text:
        down = Quartz.CGEventCreateKeyboardEvent(src, 0, True)
        up = Quartz.CGEventCreateKeyboardEvent(src, 0, False)
        Quartz.CGEventKeyboardSetUnicodeString(down, 1, char)
        Quartz.CGEventKeyboardSetUnicodeString(up, 1, char)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        time.sleep(0.001)


def _clean_line(line: str) -> str:
    """Strip whisper-stream ANSI codes and timestamp markers."""
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    line = re.sub(r"\[\d+:\d+:\d+\.\d+ --> \d+:\d+:\d+\.\d+\s*\]", "", line)
    return line.strip()


class DictationService:
    """Background dictation service — streams ASR to keyboard."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._last_text = ""

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def available(self) -> bool:
        return whisper_stream_available()

    def start(self):
        if self._running:
            return
        if not self.available:
            raise RuntimeError(f"whisper-stream not found at {WHISPER_STREAM_BIN}")
        self._running = True
        self._last_text = ""
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()
        print("[dictate] Started.")

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._proc:
            self._proc.terminate()
            self._proc = None
        print("[dictate] Stopped.")

    def _stream_loop(self):
        self._proc = subprocess.Popen(
            [
                WHISPER_STREAM_BIN,
                "-m",
                WHISPER_STREAM_MODEL,
                "--language",
                "en",
                "--step",
                "500",
                "--length",
                "5000",
                "--keep",
                "200",
                "--prompt",
                VOCAB_PROMPT,
                "--no-timestamps",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        try:
            for raw_line in self._proc.stdout:
                if not self._running:
                    break

                text = _clean_line(raw_line)
                if not text:
                    continue

                # Only type the NEW part not in last output
                if text.startswith(self._last_text):
                    new_part = text[len(self._last_text) :].lstrip()
                elif self._last_text and self._last_text in text:
                    new_part = text[text.index(self._last_text) + len(self._last_text) :].lstrip()
                else:
                    new_part = text

                if new_part:
                    _type_text(new_part + " ")

                self._last_text = text

        except Exception as e:
            print(f"[dictate] Error: {e}")
        finally:
            if self._proc:
                self._proc.terminate()
                self._proc = None
            self._running = False
