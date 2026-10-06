import pathlib
import re
import sys
import unittest

import numpy as np


TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import generate_mfcc_reference as reference


def generated_array(name, dtype):
    source = (TOOLS_DIR.parent / "main" / "generated" / "mfcc_tables.cc").read_text(
        encoding="ascii"
    )
    match = re.search(rf"const [^;]+ {name}\[\d+\] = \{{(.*?)\}};", source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Array gerado ausente: {name}")
    return np.fromstring(match.group(1).replace("f", ""), sep=",", dtype=dtype)


def firmware_style_mfcc(pcm16):
    window = generated_array("mfcc_window", np.float32)
    dct = generated_array("mfcc_dct", np.float32).reshape(reference.N_MFCC, reference.N_MELS)
    mel_basis = generated_array("mfcc_mel_basis", np.float32).reshape(
        reference.N_MELS, reference.N_FFT // 2 + 1
    )
    mel_db = np.empty((reference.N_MELS, 49), dtype=np.float32)

    for frame in range(mel_db.shape[1]):
        real = pcm16[frame * reference.HOP_LENGTH:frame * reference.HOP_LENGTH + reference.N_FFT].astype(np.float32)
        real *= np.float32(1.0 / 32768.0) * window
        spectrum = np.fft.rfft(real)
        power = np.abs(spectrum) ** 2
        mel_db[:, frame] = 10.0 * np.log10(np.maximum(mel_basis @ power, 1.0e-10))

    mel_db = np.maximum(mel_db, np.max(mel_db) - 80.0)
    features = dct @ mel_db
    output = np.clip(
        np.rint(features / reference.QUANT_SCALE + reference.QUANT_ZERO_POINT),
        -128,
        127,
    ).astype(np.int8)

    return output


class MfccFftContractTests(unittest.TestCase):
    def test_firmware_preprocessing_matches_the_training_reference(self):
        sample_rate, pcm = reference.wav.read(TOOLS_DIR / "inmp441_capture.wav")
        self.assertEqual(sample_rate, reference.SR)
        if pcm.dtype == np.int32:
            pcm = (pcm >> 16).astype(np.int16)
        else:
            pcm = pcm.astype(np.int16)
        pcm = pcm[:reference.SR]
        expected = generated_array("expected_mfcc_output", np.int8).reshape(
            reference.N_MFCC, 49
        )
        actual = firmware_style_mfcc(pcm)
        delta = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
        self.assertLessEqual(int(delta.max()), 1)


if __name__ == "__main__":
    unittest.main()
