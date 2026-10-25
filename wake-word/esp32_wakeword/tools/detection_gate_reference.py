from pathlib import Path
import re


_FIRMWARE = (Path(__file__).resolve().parents[1] / "main/detection_gate.h").read_text()


class DetectionGate:
    threshold = float(re.search(r"kThreshold\s*=\s*([0-9.]+)f;", _FIRMWARE).group(1))
    high_threshold = float(re.search(r"kHighConfidenceThreshold\s*=\s*([0-9.]+)f;", _FIRMWARE).group(1))
    support_threshold = float(re.search(r"kSupportThreshold\s*=\s*([0-9.]+)f;", _FIRMWARE).group(1))
    cooldown_ms = 2_000

    def __init__(self) -> None:
        self._history: list[float] = []
        self._last_detection_ms = -self.cooldown_ms

    def reset_confirmation(self) -> None:
        self._history.clear()

    def accept(self, score: float, now_ms: int) -> bool:
        self._history.append(score)
        self._history = self._history[-3:]
        if now_ms - self._last_detection_ms < self.cooldown_ms:
            return False
        normal = score >= self.threshold and sum(s >= self.threshold for s in self._history) >= 2
        supported = (score >= self.support_threshold
                     and sum(s >= self.support_threshold for s in self._history) >= 2
                     and max(self._history) >= self.high_threshold)
        if not normal and not supported:
            return False
        self._last_detection_ms = now_ms
        return True
