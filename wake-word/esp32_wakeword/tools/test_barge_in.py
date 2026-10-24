from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main"


def test_busy_request_does_not_disable_wakeword():
    app = (MAIN / "app_main.cc").read_text()
    assert "if (upload_worker.Busy()) continue;" not in app
    assert "upload_worker.Interruptible()" in app
    assert "upload_worker.Cancel();" in app
    assert "restart_pending = true" in app
    assert "if (restart_pending)" in app


def test_cancellation_wakes_socket_without_cross_thread_client_cleanup():
    source = (MAIN / "upload_cancellation.cc").read_text()
    assert "shutdown(socket_, SHUT_RDWR)" in source
    assert "esp_http_client_cleanup" not in source
    assert "close(socket_" not in source
    assert "xSemaphoreTake" in source


def test_uploader_checks_cancel_before_parsing_and_releases_socket_before_cleanup():
    source = (MAIN / "audio_uploader.cc").read_text()
    assert "HTTP_EVENT_ON_CONNECTED" in source
    assert "HTTP_EVENT_DISCONNECTED" in source
    assert "PublishSocket(esp_http_client_get_socket" in source
    assert "cancellation->Cancelled()" in source
    assert source.rindex("DetachSocket()") < source.rindex("esp_http_client_cleanup(client)")


def test_consumer_stop_is_nonblocking_and_does_not_consume_producer_ack():
    source = (MAIN / "audio_speaker.h").read_text()
    assert "void RequestStop() { abort_ = true; }" in source
    worker = (MAIN / "audio_upload_worker.cc").read_text()
    assert "cancellation_.Cancel();" in worker
    assert "speaker_.RequestStop();" in worker
    assert "cancellation_.Reset();" in worker


def test_inference_runs_on_other_core_than_speaker_and_upload():
    source = (MAIN / "app_main.cc").read_text()
    assert '"nuclea", CONFIG_ESP_MAIN_TASK_STACK_SIZE' in source
    assert "nullptr, 4, nullptr, 1)" in source
