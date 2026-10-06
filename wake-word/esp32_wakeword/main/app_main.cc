#include <algorithm>
#include <cstring>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "audio_capture.h"
#include "detection_gate.h"
#include "mfcc.h"
#include "status_led.h"
#include "wakeword_detector.h"

namespace {
constexpr const char* kTag = "NUCLEA_WAKEWORD";
constexpr size_t kWindowSamples = 16000;
constexpr size_t kFeatureBytes = 13 * 49;
constexpr size_t kInferenceStrideSamples = 8 * 320;  // 160 ms at 16 kHz.
constexpr int64_t kTelemetryIntervalMs = 1000;
int64_t NowMs() { return esp_timer_get_time() / 1000; }
}

extern "C" void app_main(void) {
    ESP_LOGI(kTag, "Iniciando wakeword Nuclea no ESP32-S3");

    StatusLed led;
    const esp_err_t led_result = led.Init();
    if (led_result == ESP_OK) led.RunSelfTest();
    else ESP_LOGW(kTag, "LED RGB indisponivel: %s", esp_err_to_name(led_result));
    AudioCapture capture;
    MFCC mfcc;
    WakewordDetector detector;
    if (capture.Init() != ESP_OK || !mfcc.init() || detector.Init() != ESP_OK) {
        ESP_LOGE(kTag, "Falha ao iniciar audio, DSP ou modelo");
        return;
    }
    if (!verify_mfcc_parity(detector.InputScale(), detector.InputZeroPoint())) {
        ESP_LOGE(kTag, "Paridade MFCC falhou; inferencia bloqueada");
        return;
    }

    DetectionGate gate;
    static int16_t audio_window[kWindowSamples] = {};
    static int8_t features[kFeatureBytes] = {};
    int16_t chunk[320];
    size_t filled = 0;
    size_t samples_since_inference = 0;
    int64_t last_telemetry = 0;
    float max_score_since_telemetry = 0.0f;
    uint32_t inferences_since_telemetry = 0;

    while (true) {
        size_t samples_read = 0;
        if (capture.ReadPcm16(chunk, sizeof(chunk) / sizeof(chunk[0]), &samples_read) != ESP_OK || samples_read == 0) continue;
        if (filled < kWindowSamples) {
            const size_t copied = std::min(samples_read, kWindowSamples - filled);
            std::memcpy(audio_window + filled, chunk, copied * sizeof(int16_t));
            filled += copied;
            if (filled < kWindowSamples) continue;
            samples_since_inference = kInferenceStrideSamples;
        } else {
            std::memmove(audio_window, audio_window + samples_read,
                         (kWindowSamples - samples_read) * sizeof(int16_t));
            std::memcpy(audio_window + kWindowSamples - samples_read, chunk, samples_read * sizeof(int16_t));
            samples_since_inference += samples_read;
        }

        if (samples_since_inference < kInferenceStrideSamples) continue;
        samples_since_inference %= kInferenceStrideSamples;

        const int64_t started_at = NowMs();
        float score = 0.0f;
        if (!mfcc.compute(audio_window, features, detector.InputScale(),
                          detector.InputZeroPoint()) ||
            detector.Infer(features, &score) != ESP_OK) continue;
        const int64_t now = NowMs();
        const int64_t inference_ms = now - started_at;
        max_score_since_telemetry = std::max(max_score_since_telemetry, score);
        ++inferences_since_telemetry;
        if (gate.Accept(score, now)) {
            ESP_LOGW(kTag, "Wakeword detectada: score=%.3f", static_cast<double>(score));
            if (led_result == ESP_OK) led.ToggleDetected();
        }
        if (now - last_telemetry >= kTelemetryIntervalMs) {
            const AudioLevel level = capture.LastLevel();
            const UBaseType_t stack_words = uxTaskGetStackHighWaterMark(nullptr);
            ESP_LOGI(kTag, "audio=%.1f dBFS peak=%d score=%.3f max_score=%.3f q_in=[%d,%d] q_out=[%d,%d] inferencias=%lu duracao=%lldms positivos=%u cooldown=%lldms led=%s stack_livre=%uB",
                      static_cast<double>(level.rms_dbfs), level.peak, static_cast<double>(score),
                      static_cast<double>(max_score_since_telemetry),
                      detector.LastInputMin(), detector.LastInputMax(),
                      detector.LastBackgroundOutput(), detector.LastWakewordOutput(),
                      static_cast<unsigned long>(inferences_since_telemetry),
                      static_cast<long long>(inference_ms),
                      gate.PositiveCount(), static_cast<long long>(gate.CooldownRemainingMs(now)),
                      led.IsGreen() ? "verde" : "apagado",
                      static_cast<unsigned>(stack_words * sizeof(StackType_t)));
            last_telemetry = now;
            max_score_since_telemetry = 0.0f;
            inferences_since_telemetry = 0;
        }
        vTaskDelay(1);
    }
}
