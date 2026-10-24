from pathlib import Path


MAIN = Path(__file__).resolve().parents[1] / "main"


def test_large_stream_buffers_use_psram_not_tls_internal_heap():
    source = (MAIN / "speaker_response.cc").read_text()
    assert "heap_caps_malloc(8192, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)" in source
    assert "heap_caps_malloc(4800, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)" in source
    assert "std::malloc" not in source


def test_parse_failures_report_location_and_memory_without_dumping_audio():
    source = (MAIN / "speaker_response.cc").read_text()
    assert "heap_caps_get_largest_free_block" in source
    assert "JSON parse failed" in source
    assert "stage=%s" in source
    assert "cJSON_InitHooks" not in source
