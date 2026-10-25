import numpy as np
import pytest

from generate_synthetic_negatives import PHRASES, VOICES, RATES, validate_negative, choose_windows, variants, group_id


def test_plan_has_requested_words_and_multiple_voices_and_patterns():
    assert len(VOICES) == 5
    assert len(RATES) == 3
    assert len(PHRASES) == 16
    for word in ("corno", "problema", "singapura", "irm\u00e3"):
        assert sum(word in text.lower() for _, text in PHRASES) >= 3
    for _, text in PHRASES:
        validate_negative(text)


@pytest.mark.parametrize("text", ["Nuclea", "Oi, N\u00faclea!", "Boa tarde nuclea"])
def test_negative_guard_rejects_wakeword(text):
    with pytest.raises(ValueError):
        validate_negative(text)


def test_windows_are_exactly_one_second_and_not_silence():
    audio = np.zeros(64000, dtype=np.float32)
    audio[16000:48000] = .1 * np.sin(np.arange(32000) * .1)
    starts = choose_windows(audio)
    assert 1 <= len(starts) <= 3
    assert starts == sorted(set(starts))
    assert all(len(audio[start:start + 16000]) == 16000 for start in starts)
    assert choose_windows(np.zeros(32000, dtype=np.float32)) == []


def test_variants_preserve_length_and_do_not_clip():
    audio = .9 * np.sin(np.arange(16000) * .1).astype(np.float32)
    noise = np.random.default_rng(4).normal(0, .03, 48000).astype(np.float32)
    output = variants(audio, noise, np.random.default_rng(3))
    assert set(output) == {"clean", "quiet", "ambient"}
    assert all(len(samples) == 16000 and np.max(np.abs(samples)) <= .981 for samples in output.values())
    assert np.sqrt(np.mean(output["quiet"] ** 2)) < np.sqrt(np.mean(output["clean"] ** 2))


def test_rates_and_augmentations_share_the_same_training_group():
    assert group_id("voice", "problema") == "synthetic:voice:problema"
