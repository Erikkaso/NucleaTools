from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_music_only_starts_before_other_devices():
    source = (ROOT / "main" / "app_main.cc").read_text()
    assert "RunSpeakerMusicTest();" in source
    assert source.index("RunSpeakerMusicTest();") < source.index("StatusLed led;")
    assert source.index("RunSpeakerMusicTest();") < source.index("MFCC mfcc;")


def test_test_filesystem_does_not_include_display_gifs():
    source = (ROOT / "main" / "CMakeLists.txt").read_text()
    assert "if(CONFIG_NUCLEA_SPEAKER_ONLY_TEST)" in source
    assert "speaker_test_data" in source
    assert "elseif(CONFIG_NUCLEA_DISPLAY_ENABLED)" in source


def test_music_is_complete_pcm_and_fits_test_partition():
    pcm = ROOT / "main" / "speaker_test_data" / "music.pcm"
    size = pcm.stat().st_size
    assert size % 2 == 0
    assert 220 < size / 48000 < 222
    assert size < 0xCF0000 - 256 * 1024
    with pcm.open("rb") as stream:
        assert stream.read(4) != b"RIFF"


def test_test_volume_does_not_replace_production_volume():
    source = (ROOT / "main" / "speaker_music_test.cc").read_text()
    assert "speaker.Init(CONFIG_NUCLEA_SPEAKER_TEST_VOLUME_PERCENT)" in source
    assert "while (true)" in source
    assert "speaker.Finish()" in source
    assert "speaker.Push" in source
