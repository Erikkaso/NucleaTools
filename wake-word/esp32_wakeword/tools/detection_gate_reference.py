class DetectionGate:
    threshold = 0.85
    high_threshold = 0.98
    cooldown_ms = 2_000

    def __init__(self) -> None:
        self._history: list[bool] = []
        self._last_detection_ms = -self.cooldown_ms

    def accept(self, score: float, now_ms: int) -> bool:
        self._history.append(score >= self.threshold)
        self._history = self._history[-3:]
        if now_ms - self._last_detection_ms < self.cooldown_ms:
            return False
        if score < self.high_threshold and sum(self._history) < 2:
            return False
        self._last_detection_ms = now_ms
        return True
