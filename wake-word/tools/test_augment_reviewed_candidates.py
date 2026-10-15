import csv
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import numpy as np

import augment_reviewed_candidates as preparation


def speech_sample():
    audio = np.zeros(16000, dtype=np.float32)
    audio[3200:12800] = 0.3 * np.sin(2 * np.pi * 440 * np.arange(9600) / 16000)
    return audio


class ReviewedAugmentationTests(unittest.TestCase):
    def test_silence_is_not_classified_as_noisy_speech(self):
        self.assertFalse(preparation.assess_noise(np.zeros(16000))["filter_recommended"])

    def test_elevated_background_is_flagged_but_clean_speech_is_not(self):
        audio = speech_sample()
        self.assertFalse(preparation.assess_noise(audio)["filter_recommended"])
        noisy = audio + np.random.default_rng(8).normal(0, 0.015, 16000)
        self.assertTrue(preparation.assess_noise(noisy)["filter_recommended"])

    def test_dominant_continuous_noise_is_also_flagged(self):
        noisy = speech_sample() * 0.05 + np.random.default_rng(9).normal(0, 0.1, 16000)
        assessment = preparation.assess_noise(noisy)
        self.assertLess(assessment["energy_range_db"], 6)
        self.assertTrue(assessment["filter_recommended"])

    def test_time_shift_does_not_discard_voice_at_window_edges(self):
        audio = np.zeros(16000, dtype=np.float32)
        audio[-1] = 0.8
        shifted, offset = preparation.safe_shift(audio, 960)
        self.assertEqual(offset, 0)
        np.testing.assert_array_equal(shifted, audio)
        audio[-1] = 0
        audio[8000] = 0.8
        shifted, offset = preparation.safe_shift(audio, 960)
        self.assertEqual(offset, 960)
        self.assertEqual(np.argmax(shifted), 8960)

    def test_variants_are_reproducible_bounded_and_one_second(self):
        first = preparation.make_variants(speech_sample(), seed=12)
        second = preparation.make_variants(speech_sample(), seed=12)
        self.assertEqual(len(first), 4)
        for (name, audio, _), (other_name, repeated, _) in zip(first, second):
            self.assertEqual(name, other_name)
            self.assertEqual(audio.shape, (16000,))
            self.assertTrue(np.isfinite(audio).all())
            self.assertLessEqual(float(np.max(np.abs(audio))), 0.981)
            np.testing.assert_array_equal(audio, repeated)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_filter_compensates_latency_and_preserves_last_samples(self):
        audio = np.zeros(16000, dtype=np.float32)
        audio[15900] = 0.7
        filtered = preparation.denoise_audio(audio, shutil.which("ffmpeg"), -44)
        self.assertEqual(filtered.shape, (16000,))
        self.assertLessEqual(abs(int(np.argmax(np.abs(filtered))) - 15900), 2)

    def test_processing_preserves_sources_groups_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            speaker = Path(temporary) / "wakeword_example"
            review = speaker / "review"
            review.mkdir(parents=True)
            for index in (1, 2):
                preparation.write_audio(review / f"candidate_{index:04d}.wav", speech_sample())
            with (speaker / "manifest.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["file", "source_file"])
                writer.writeheader()
                for index in (1, 2):
                    writer.writerow({"file": f"review/candidate_{index:04d}.wav", "source_file": "session.ogg"})
            original = review / "candidate_0001.wav"
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            report = preparation.process_speaker(speaker, shutil.which("ffmpeg"), seed=42)
            self.assertEqual(report["clean_count"], 2)
            self.assertEqual(report["augmented_count"], 8)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
            with (speaker / "metadata.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 10)
            self.assertEqual(len({row["group_id"] for row in rows}), 1)
            self.assertTrue(all((speaker / row["file"]).is_file() for row in rows))
            with self.assertRaises(FileExistsError):
                preparation.process_speaker(speaker, shutil.which("ffmpeg"), seed=42)


if __name__ == "__main__":
    unittest.main()
