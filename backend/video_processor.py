"""Video frame extraction with timestamps.

Frames are sampled every ``VIDEO_FRAME_INTERVAL`` seconds using OpenCV (headless,
no GUI dependencies) and yielded together with their precise offset in seconds so
that a search result can be opened at the matching moment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, Optional

import cv2
from PIL import Image

log = logging.getLogger(__name__)

# Hard safety cap so a single very long video cannot blow up the index.
MAX_FRAMES = 600
# Fallback frame rate when the container does not report one.
DEFAULT_FPS = 25.0


@dataclass
class Frame:
    timestamp: float
    image: Image.Image


def probe_duration(path: str) -> Optional[float]:
    """Return the duration in seconds, or ``None`` when it cannot be determined."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        if fps > 0 and frames > 0:
            return float(frames / fps)
        return None
    finally:
        capture.release()


def iter_frames(path: str, interval: float, max_frames: int = MAX_FRAMES) -> Iterator[Frame]:
    """Yield one :class:`Frame` every ``interval`` seconds of the video."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise OSError(f"cannot open video: {path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or DEFAULT_FPS
    if fps <= 0:
        fps = DEFAULT_FPS
    step = max(1, int(round(fps * float(interval))))

    emitted = 0
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                yield Frame(index / fps, Image.fromarray(rgb))
                emitted += 1
                if emitted >= max_frames:
                    log.debug("Reached %d-frame cap for %s", max_frames, path)
                    break
            index += 1
    finally:
        capture.release()


def probe_audio_duration(path: str) -> Optional[float]:
    """Return an audio/video file duration in seconds using ``ffprobe``.

    OpenCV cannot inspect audio-only containers, so we fall back to ffprobe when
    it is available on the system.
    """
    import shutil
    import subprocess

    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        value = result.stdout.strip()
        return float(value) if value else None
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
