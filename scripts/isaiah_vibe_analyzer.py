"""
isaiah_vibe_analyzer.py — focus and posture analytics for Kristina's 3-minute sweeps.

Uses OpenCV cascade detectors for:
  - Eye openness (eye strain / fatigue detection via eye aspect ratio proxy)
  - Head tilt (posture detection via eye-center geometry)
  - Gaze / screen engagement (face position relative to frame center)

Outputs a VibeState. When streak counters hit limits, sends haptic pulse
to Callan's relay on port 7901.

Swap point: replace _analyze() with a MediaPipe Tasks or MiniCPM-V call
when the 4090 home build arrives.

Usage:
    from isaiah_vibe_analyzer import VibeAnalyzer
    analyzer = VibeAnalyzer()
    state = analyzer.analyze(FACE_PATH)
    if state.needs_break and state.pulse_type:
        analyzer.send_haptic(state.pulse_type)
"""

import cv2
import numpy as np
import logging
import urllib.request
import json
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("isaiah.vibe")

VIBE_RELAY       = "http://localhost:7901"
HAPTIC_ENDPOINT  = f"{VIBE_RELAY}/vibe"

# ── Tunable thresholds ─────────────────────────────────────────────────────
EYE_OPEN_RATIO_MIN = 0.28   # eye h/w below this = narrowed/strained
HEAD_TILT_DEGREES  = 12.0   # tilt past this = posture flag
GAZE_CENTER_MARGIN = 0.30   # face center must be within this fraction of frame center
STRAIN_COUNT_LIMIT = 4      # consecutive strained pings (~12 min) → ISAIAH_REST
POSTURE_COUNT_LIMIT = 3     # consecutive posture flags (~9 min) → ISAIAH_POSTURE


@dataclass
class VibeState:
    eye_open_ratio: float   = 0.0    # avg eye h/w — lower = more closed/strained
    head_tilt_deg: float    = 0.0    # degrees from horizontal
    gaze_offset: float      = 0.0    # normalized distance of face center from frame center

    eyes_straining: bool    = False
    posture_flagged: bool   = False
    looking_away: bool      = False
    needs_break: bool       = False

    pulse_type: Optional[str] = None  # "ISAIAH_REST" or "ISAIAH_POSTURE"
    notes: str              = ""
    landmarks_found: bool   = False


class VibeAnalyzer:
    """
    Stateful vibe analyzer. One instance lives for the session —
    streak counters persist between 3-minute Study Buddy pings.
    """

    def __init__(self):
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )
        self._strain_streak  = 0
        self._posture_streak = 0

    def analyze(self, image_path: str) -> VibeState:
        img = cv2.imread(image_path)
        if img is None:
            return VibeState(notes=f"Could not load: {image_path}")

        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        h, w = gray.shape

        # Detect face
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            return VibeState(notes="No face detected — skipping vibe check")

        # Use largest face
        fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])
        face_roi = gray[fy:fy + fh, fx:fx + fw]

        # Detect eyes within face ROI
        eyes = self._eye_cascade.detectMultiScale(
            face_roi, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20)
        )

        eye_open_ratio = 0.0
        head_tilt_deg  = 0.0
        eye_centers    = []

        if len(eyes) >= 2:
            # Sort by x position — left eye first
            eyes_sorted = sorted(eyes, key=lambda e: e[0])[:2]
            ratios = []
            for (ex, ey, ew, eh) in eyes_sorted:
                ratio = eh / ew if ew > 0 else 0.0
                ratios.append(ratio)
                center_x = fx + ex + ew // 2
                center_y = fy + ey + eh // 2
                eye_centers.append((center_x, center_y))
            eye_open_ratio = float(np.mean(ratios))

            # Head tilt = angle of line between two eye centers from horizontal
            dx = eye_centers[1][0] - eye_centers[0][0]
            dy = eye_centers[1][1] - eye_centers[0][1]
            head_tilt_deg = float(abs(np.degrees(np.arctan2(dy, dx))))
            landmarks_found = True
        elif len(eyes) == 1:
            ex, ey, ew, eh = eyes[0]
            eye_open_ratio = eh / ew if ew > 0 else 0.0
            landmarks_found = True
        else:
            landmarks_found = False

        # Gaze proxy: how far is face center from frame center
        face_cx = fx + fw / 2
        face_cy = fy + fh / 2
        gaze_offset = float(
            ((face_cx / w - 0.5) ** 2 + (face_cy / h - 0.5) ** 2) ** 0.5
        )

        # Interpret readings
        eyes_straining  = landmarks_found and eye_open_ratio < EYE_OPEN_RATIO_MIN
        posture_flagged = landmarks_found and head_tilt_deg > HEAD_TILT_DEGREES
        looking_away    = gaze_offset > GAZE_CENTER_MARGIN

        # Update streaks
        if eyes_straining:
            self._strain_streak += 1
        else:
            self._strain_streak = max(0, self._strain_streak - 1)

        if posture_flagged:
            self._posture_streak += 1
        else:
            self._posture_streak = max(0, self._posture_streak - 1)

        needs_break = (self._strain_streak >= STRAIN_COUNT_LIMIT or
                       self._posture_streak >= POSTURE_COUNT_LIMIT)

        pulse_type = None
        if needs_break:
            if self._strain_streak >= STRAIN_COUNT_LIMIT:
                pulse_type = "ISAIAH_REST"
                self._strain_streak = 0
            elif self._posture_streak >= POSTURE_COUNT_LIMIT:
                pulse_type = "ISAIAH_POSTURE"
                self._posture_streak = 0

        parts = [f"eye_ratio={eye_open_ratio:.3f}", f"tilt={head_tilt_deg:.1f}°",
                 f"gaze={gaze_offset:.3f}", f"eyes={len(eyes)}"]
        if eyes_straining:
            parts.append(f"STRAIN(streak={self._strain_streak})")
        if posture_flagged:
            parts.append(f"POSTURE(streak={self._posture_streak})")
        if looking_away:
            parts.append("GAZE_OFF")

        log.info("[vibe] %s", " | ".join(parts))

        return VibeState(
            eye_open_ratio=eye_open_ratio,
            head_tilt_deg=head_tilt_deg,
            gaze_offset=gaze_offset,
            eyes_straining=eyes_straining,
            posture_flagged=posture_flagged,
            looking_away=looking_away,
            needs_break=needs_break,
            pulse_type=pulse_type,
            notes=" | ".join(parts),
            landmarks_found=landmarks_found,
        )

    def send_haptic(self, pulse_type: str) -> bool:
        """Send haptic pulse to Callan's relay on port 7901."""
        try:
            body = json.dumps({"pattern": pulse_type}).encode("utf-8")
            req = urllib.request.Request(
                HAPTIC_ENDPOINT, data=body,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=2)
            log.info("[vibe] Haptic sent: %s", pulse_type)
            return True
        except Exception as e:
            log.warning("[vibe] Haptic relay unreachable: %s", e)
            return False

    def reset_streaks(self):
        """Call after confirmed absence or long break."""
        self._strain_streak  = 0
        self._posture_streak = 0
