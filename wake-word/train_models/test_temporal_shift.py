import unittest

import numpy as np

from train_noise_robust_v1 import shift_audio_window


class ShiftAudioWindowTest(unittest.TestCase):
    def test_shifts_audio_right_with_silence(self):
        audio = np.zeros(16000, dtype=np.float32)
        audio[:4] = [1.0, 2.0, 3.0, 4.0]

        shifted = shift_audio_window(audio, 2)

        np.testing.assert_array_equal(shifted[:4], [0.0, 0.0, 1.0, 2.0])
        self.assertEqual(len(shifted), 16000)

    def test_shifts_audio_left_with_silence(self):
        audio = np.zeros(16000, dtype=np.float32)
        audio[:4] = [1.0, 2.0, 3.0, 4.0]

        shifted = shift_audio_window(audio, -2)

        np.testing.assert_array_equal(shifted[:4], [3.0, 4.0, 0.0, 0.0])
        self.assertEqual(len(shifted), 16000)


if __name__ == "__main__":
    unittest.main()
