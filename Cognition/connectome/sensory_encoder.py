"""Convert camera frames into pre-linguistic visual stimuli.

The encoder deliberately does not detect semantic classes such as people or
walls.  It extracts only motion, expansion (looming), luminance and contrast.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import cv2
import numpy as np


@dataclass
class SensoryState:
    motion_left: float = 0.0
    motion_right: float = 0.0
    looming: float = 0.0
    luminance: float = 0.0
    contrast: float = 0.0
    frame_valid: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SensoryEncoder:
    """Dense optical-flow encoder suitable for a Jetson Nano camera stream."""

    def __init__(self, width: int = 160, height: int = 120, smoothing: float = 0.7):
        self.size = (max(32, int(width)), max(24, int(height)))
        self.smoothing = float(np.clip(smoothing, 0.0, 0.99))
        self._previous_gray: Optional[np.ndarray] = None
        self._smoothed = SensoryState()

    def reset(self) -> None:
        self._previous_gray = None
        self._smoothed = SensoryState()

    def encode(self, frame: np.ndarray) -> Dict[str, Any]:
        if frame is None or frame.size == 0:
            return SensoryState().to_dict()

        small = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        else:
            gray = small
        gray = gray.astype(np.uint8, copy=False)

        luminance = float(np.mean(gray) / 255.0)
        contrast = float(np.std(gray) / 127.5)
        contrast = float(np.clip(contrast, 0.0, 1.0))

        if self._previous_gray is None:
            self._previous_gray = gray
            self._smoothed = SensoryState(
                luminance=luminance,
                contrast=contrast,
                frame_valid=True,
            )
            return self._smoothed.to_dict()

        flow = cv2.calcOpticalFlowFarneback(
            self._previous_gray,
            gray,
            None,
            pyr_scale=0.5,
            levels=2,
            winsize=15,
            iterations=2,
            poly_n=5,
            poly_sigma=1.1,
            flags=0,
        )
        self._previous_gray = gray

        magnitude = np.linalg.norm(flow, axis=2)
        # About four pixels/frame is already a strong stimulus at 160x120.
        left_motion = float(np.clip(np.mean(magnitude[:, : self.size[0] // 2]) / 4.0, 0.0, 1.0))
        right_motion = float(np.clip(np.mean(magnitude[:, self.size[0] // 2 :]) / 4.0, 0.0, 1.0))

        yy, xx = np.mgrid[0 : self.size[1], 0 : self.size[0]].astype(np.float32)
        cx = (self.size[0] - 1) * 0.5
        cy = (self.size[1] - 1) * 0.5
        rx = xx - cx
        ry = yy - cy
        radius = np.sqrt(rx * rx + ry * ry) + 1e-6
        radial_flow = (flow[..., 0] * rx + flow[..., 1] * ry) / radius
        # Ignore the unstable centre and inward (receding) flow.
        mask = radius > min(self.size) * 0.12
        expansion = np.maximum(radial_flow[mask], 0.0)
        looming = float(np.clip(np.mean(expansion) / 2.0, 0.0, 1.0))

        raw = SensoryState(
            motion_left=left_motion,
            motion_right=right_motion,
            looming=looming,
            luminance=luminance,
            contrast=contrast,
            frame_valid=True,
        )
        a = self.smoothing
        previous = self._smoothed
        self._smoothed = SensoryState(
            motion_left=a * previous.motion_left + (1.0 - a) * raw.motion_left,
            motion_right=a * previous.motion_right + (1.0 - a) * raw.motion_right,
            looming=a * previous.looming + (1.0 - a) * raw.looming,
            luminance=a * previous.luminance + (1.0 - a) * raw.luminance,
            contrast=a * previous.contrast + (1.0 - a) * raw.contrast,
            frame_valid=True,
        )
        return self._smoothed.to_dict()
