from evaluate_synthetic_negatives import events


def test_strict_policy_rejects_an_isolated_high_peak():
    scores = [0.0, 0.996, 0.1, 0.1]
    assert events(scores, strict=False) == 1
    assert events(scores, strict=True) == 0


def test_strict_policy_preserves_confirmed_detection():
    scores = [0.0, 0.95, 0.95, 0.1]
    assert events(scores, strict=False) == 1
    assert events(scores, strict=True) == 1


def test_strict_policy_preserves_cooldown():
    assert events([0.996] * 8, strict=True) == 1
