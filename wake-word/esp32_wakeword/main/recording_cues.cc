#include "recording_cues.h"
#include "esp_log.h"

#ifdef CONFIG_NUCLEA_RECORDING_SFX_ENABLED
extern const uint8_t on_start[] asm("_binary_onsfx_pcm_start");
extern const uint8_t on_end[] asm("_binary_onsfx_pcm_end");
extern const uint8_t off_start[] asm("_binary_offsfx_pcm_start");
extern const uint8_t off_end[] asm("_binary_offsfx_pcm_end");
#endif

esp_err_t PlayRecordingCue(AudioSpeaker& speaker, RecordingCue cue) {
#ifdef CONFIG_NUCLEA_RECORDING_SFX_ENABLED
    const uint8_t* pcm = cue == RecordingCue::kOn ? on_start : off_start;
    const size_t bytes = cue == RecordingCue::kOn ? on_end - on_start : off_end - off_start;
    ESP_LOGI("RECORDING_SFX", "%s: %u bytes PCM", cue == RecordingCue::kOn ? "onsfx" : "offsfx", unsigned(bytes));
    if (!bytes || bytes % 2) return ESP_ERR_INVALID_SIZE;
    esp_err_t result = speaker.Begin();
    if (result != ESP_OK) return result;
    if (!speaker.Push(pcm, bytes)) {
        speaker.Abort();
        result = ESP_FAIL;
    } else {
        result = speaker.Finish();
    }
    if (result != ESP_OK)
        ESP_LOGW("RECORDING_SFX", "Falha no efeito: %s", esp_err_to_name(result));
    return result;
#else
    (void)speaker;
    (void)cue;
    return ESP_OK;
#endif
}
