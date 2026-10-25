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
        "sleep2.gif", "wake-open2.gif", "wake-open2-reverse.gif", "idle.gif", "smile.gif",
        "elegant.gif", "dizzy.gif", "angry.gif", "cry.gif", "loadingtrans.gif", "loadingtrans-reverse.gif", "loading.gif",
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
    assert "due = DisplayFrameDeadline(started, rendered, delay, last_frame);" in display
    assert display.index("if (!Submit(") < display.index("due = DisplayFrameDeadline")
    assert "last_frame && !WaitLcdIdle()" in display
    assert "animation_->LastFrame()" in display


def test_display_does_not_compete_with_inference_on_core_one():
    display = (ROOT / "main/robot_display.cc").read_text()
    assert '"robot_display", 6144, this, 1, nullptr, 0)' in display
    assert "decode_avg_ms=" in display
    assert "lcd_avg_ms=" in display
    assert "portTICK_PERIOD_MS" in display


def test_telemetry_uses_idf_stack_bytes_without_multiplying_by_word_size():
    app = (ROOT / "main/app_main.cc").read_text()
    assert "stack_words * sizeof(StackType_t)" not in app
    assert "static_cast<unsigned>(stack_bytes)" in app


def test_http_auth_rejection_has_an_actionable_secret_free_diagnostic():
    upload = (ROOT / "main/audio_uploader.cc").read_text()
    assert "status == 401 || status == 403" in upload
    assert "Confira X-Nuclea-Key no portal" in upload


def test_cancelled_response_flag_is_cleared_after_worker_finishes():
    worker = (ROOT / "main/audio_upload_worker.cc").read_text()
    poll = worker.split("bool AudioUploadWorker::Poll(", 1)[1].split("bool AudioUploadWorker::PollCue", 1)[0]
    assert "if (cancellation_.Cancelled()) response_started_ = false;" in poll
    assert poll.index("xQueueReceive(results_") < poll.index("response_started_ = false;")


def test_sleep_wake_event_discards_only_sleep_loop_and_old_frame_deadline():
    source = (ROOT / "main/robot_display.cc").read_text()
    branch = source.split("case EventKind::kWake:", 1)[1].split("case EventKind::kReady:", 1)[0]
    assert "was_sleeping" in branch
    assert "if (was_sleeping)" in branch
    assert "animation_->Close();" in branch
    assert "loop_open = false;" in branch
    assert "transition_finished = false;" in branch
    assert "due = 0;" in branch


def test_transitions_play_from_flash_without_psram_frame_cache():
    display = (ROOT / "main/robot_display.cc").read_text()
    assert '"/robot/wake-open2-reverse.gif"' in display and '"/robot/wake-open2.gif"' in display
    assert "transition_ +" not in display and "kCacheLimit" not in display


def test_speaker_output_goes_through_highpass_and_limiter():
    speaker = (ROOT / "main/audio_speaker.cc").read_text()
    assert "dsp_.Process(" in speaker and "dsp_.Reset();" in speaker
    assert "* volume_percent_ / 100" not in speaker
    assert "../tools/speaker_dsp_tests.cc" in (ROOT / "main/CMakeLists.txt").read_text()


def test_piezo_overrides_pcnt_pullup_and_keeps_native_usb_free():
    sensor = (ROOT / "main/piezo_sensor.cc").read_text()
    assert sensor.index("pcnt_new_channel") < sensor.index("gpio_pullup_dis")
    assert "CONFIG_NUCLEA_PIEZO_GPIO=1" in (ROOT / "sdkconfig").read_text().splitlines()
    assert "../tools/piezo_tests.cc" in (ROOT / "main/CMakeLists.txt").read_text()
