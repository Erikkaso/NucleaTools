import unittest

from record_inmp441 import PcmStreamDecoder, STREAM_MAGIC


class PcmStreamDecoderTest(unittest.TestCase):
    def test_waits_for_fragmented_magic_and_emits_complete_pcm_samples(self):
        decoder = PcmStreamDecoder()

        self.assertEqual(decoder.feed(b"boot" + STREAM_MAGIC[:2]), b"")
        self.assertEqual(decoder.feed(STREAM_MAGIC[2:] + b"\x01"), b"")
        self.assertEqual(decoder.feed(b"\x00\x02\x00\x03"), b"\x01\x00\x02\x00")
        self.assertEqual(decoder.feed(b"\x00"), b"\x03\x00")

    def test_reports_fragmented_i2s_initialization_error(self):
        decoder = PcmStreamDecoder()

        self.assertEqual(decoder.feed(b"ER"), b"")
        with self.assertRaisesRegex(RuntimeError, "I2S"):
            decoder.feed(b"RO")


if __name__ == "__main__":
    unittest.main()
