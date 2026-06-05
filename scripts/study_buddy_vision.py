"""
study_buddy_vision.py — lightweight human presence detection for Study Buddy.

Replaces raw pixel-diff inactivity check with face detection + motion scoring.
Designed to be a drop-in module now, and a swap point for MiniCPM-V 4.5 (Q3-Q4).

Usage:
    from study_buddy_vision import PresenceDetector
    detector = PresenceDetector()
    result = detector.analyze(FACE_PATH)
    if not result.present:
        fire_nudge()
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional

_HAAR_FACE = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
_HAAR_BODY = cv2.data.haarcascades + "haarcascade_fullbody.xml"

# Motion score below this = person hasn't moved (inactivity candidate)
MOTION_INACTIVE_THRESHOLD = 3.0
# Motion score above this = definite movement, person is active
MOTION_ACTIVE_THRESHOLD = 8.0


@dataclass
class PresenceResult:
    present: bool           # someone detected in frame
    confidence: float       # 0.0–1.0
    face_count: int         # faces found by cascade
    largest_face_pct: float # largest face area as fraction of total frame
    motion_score: float     # mean pixel diff vs previous frame (0 = no change)
    notes: str = ""


class PresenceDetector:
    """
    Stateful presence detector. Keep one instance alive across pings so the
    previous-frame comparison stays valid between Study Buddy checks.
    """

    def __init__(self):
        self._face_cascade = cv2.CascadeClassifier(_HAAR_FACE)
        self._body_cascade = cv2.CascadeClassifier(_HAAR_BODY)
        self._prev_gray: Optional[np.ndarray] = None

    def analyze(self, image_path: str) -> PresenceResult:
        """
        Analyze a face-cam image for human presence.

        Detection priority:
          1. Face detected          → present, high confidence
          2. No face, body detected → present, medium confidence
          3. No face/body, motion   → probably present (moved out of frame)
          4. Nothing                → absent
        """
        img = cv2.imread(image_path)
        if img is None:
            return PresenceResult(
                present=False, confidence=0.0, face_count=0,
                largest_face_pct=0.0, motion_score=0.0,
                notes=f"Could not load: {image_path}"
            )

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)  # improve detection in low light
        h, w = gray.shape

        # Face detection
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
        )
        face_count = int(len(faces))
        largest_face_pct = 0.0
        if face_count > 0:
            areas = [int(fw) * int(fh) for (_, _, fw, fh) in faces]
            largest_face_pct = max(areas) / (w * h)

        # Motion score vs previous frame
        motion_score = 0.0
        if self._prev_gray is not None:
            prev = cv2.resize(self._prev_gray, (w, h))
            diff = cv2.absdiff(gray, prev)
            motion_score = float(diff.mean())
        self._prev_gray = gray.copy()

        # Presence decision tree
        if face_count > 0:
            confidence = min(1.0, 0.65 + largest_face_pct * 2.0)
            present = True
            notes = f"{face_count} face(s) detected (largest {largest_face_pct*100:.1f}% of frame)"
        else:
            # Try full-body as fallback (useful when she's lying down, camera angle off)
            bodies = self._body_cascade.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=3, minSize=(60, 120)
            )
            body_count = int(len(bodies))

            if body_count > 0:
                confidence = 0.55
                present = True
                notes = f"Body detected (no face), motion={motion_score:.1f}"
            elif motion_score > MOTION_ACTIVE_THRESHOLD:
                confidence = min(0.5, motion_score / 40.0)
                present = True
                notes = f"Motion only (score={motion_score:.1f}), no face/body in frame"
            else:
                confidence = 0.0
                present = False
                notes = f"No presence (motion={motion_score:.1f})"

        return PresenceResult(
            present=present,
            confidence=confidence,
            face_count=face_count,
            largest_face_pct=largest_face_pct,
            motion_score=motion_score,
            notes=notes,
        )

    def is_inactive(self, result: PresenceResult) -> bool:
        """
        True if someone is present but hasn't moved — inactivity candidate.
        Used to decide whether to fire a nudge.
        """
        return result.present and result.motion_score < MOTION_INACTIVE_THRESHOLD

    def reset(self):
        """Clear previous-frame memory (call after long gaps or session restart)."""
        self._prev_gray = None
