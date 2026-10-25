from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_normal_image_contains_only_animation_files():
    cmake = (ROOT / "main/CMakeLists.txt").read_text()
    config = (ROOT / "main/Kconfig.projbuild").read_text()
    assert "speaker_test_data" not in cmake
    assert "SPEAKER_ONLY_TEST" not in config
    assert "speaker_music_test" not in cmake
    assert not (ROOT / "main/speaker_test_data/music.pcm").exists()
    assets = ROOT.parent / "nuclea_gif_player_fixed/data"
    assert {p.name for p in assets.iterdir() if p.is_file()} == {
        "sleep.gif", "wake.gif", "nuclea-blink.gif", "smile.gif",
        "elegant.gif", "dizzy.gif", "angry.gif", "cry.gif",
    }


def test_reply_expression_is_not_triggered_by_local_sound_effects():
    app = (ROOT / "main/app_main.cc").read_text()
    assert "upload_worker.TakeResponseStarted()" in app
    assert "display.Response();" in app
    worker = (ROOT / "main/audio_upload_worker.cc").read_text()
    assert "response_started_.exchange(false)" in (ROOT / "main/audio_upload_worker.h").read_text()
    assert "&self->response_started_" in worker


def test_new_expressions_are_optional_and_switch_only_at_cycle_end():
    display = (ROOT / "main/robot_display.cc").read_text()
    assert "state.CycleComplete" in display
    assert "state.Response" in display
    assert "motion.Observe" in display
    for name in ("smile", "elegant", "dizzy", "angry", "cry"):
        assert f'/robot/{name}.gif' in display
    assert "GIF opcional" in display


def test_last_frame_hold_is_measured_after_lcd_transfer():
    display = (ROOT / "main/robot_display.cc").read_text()
    assert "due = NowMs() + std::max(delay, 10);" in display
    assert display.index("if (!Flush(pixels") < display.index("due = NowMs() + std::max(delay, 10);")


def test_cancelled_response_flag_is_cleared_after_worker_finishes():
    worker = (ROOT / "main/audio_upload_worker.cc").read_text()
    poll = worker.split("bool AudioUploadWorker::Poll(", 1)[1].split("bool AudioUploadWorker::PollCue", 1)[0]
    assert "if (cancellation_.Cancelled()) response_started_ = false;" in poll
    assert poll.index("xQueueReceive(results_") < poll.index("response_started_ = false;")
