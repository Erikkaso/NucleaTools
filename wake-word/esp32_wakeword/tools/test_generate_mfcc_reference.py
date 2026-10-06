import pathlib
import sys
import unittest

import numpy as np


TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import generate_mfcc_reference as reference


class DspTableTests(unittest.TestCase):
    def test_process_audio_uses_the_supplied_model_quantization(self):
        mfcc = np.asarray([[-100.0, 0.0, 100.0]], dtype=np.float32)

        first = reference.quantize_mfcc(mfcc, 3.209484815597534, 69)
        second = reference.quantize_mfcc(mfcc, 3.1064834594726562, 76)

        self.assertFalse(np.array_equal(first, second))

    def test_float_formatter_emits_valid_cpp_literals_for_integers(self):
        rendered = reference._format_float([0.0, 1.0, -0.0, 1.25, 1.0e-5])

        self.assertIn("0.0f", rendered)
        self.assertIn("1.0f", rendered)
        self.assertIn("-0.0f", rendered)
        self.assertNotIn(" 0f", rendered)
        self.assertNotIn(" 1f", rendered)

    def test_build_dsp_tables_matches_the_mfcc_contract(self):
        window, dct, bit_reverse, fft_cos, fft_sin = reference.build_dsp_tables()

        self.assertEqual(window.shape, (reference.N_FFT,))
        self.assertEqual(dct.shape, (reference.N_MFCC, reference.N_MELS))
        self.assertEqual(bit_reverse.shape, (reference.N_FFT,))
        self.assertEqual(fft_cos.shape, (reference.N_FFT // 2,))
        self.assertEqual(fft_sin.shape, (reference.N_FFT // 2,))
        self.assertTrue(np.allclose(window[:56], 0.0))
        self.assertTrue(np.allclose(window[-56:], 0.0))
        self.assertEqual(int(bit_reverse[0]), 0)
        self.assertEqual(int(bit_reverse[1]), 256)
        self.assertAlmostEqual(float(fft_cos[0]), 1.0, places=6)
        self.assertAlmostEqual(float(fft_sin[0]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
