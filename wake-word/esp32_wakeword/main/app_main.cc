#include <algorithm>
#include <cstring>
#include <string>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "audio_capture.h"
#include "audio_recorder.h"
#include "audio_upload_worker.h"
#include "detection_gate.h"
#include "mfcc.h"
#include "status_led.h"
#include "wakeword_detector.h"
#include "wifi_station.h"
#include "robot_display.h"
#include "speaker_music_test.h"

namespace {
constexpr const char* kTag = "NUCLEA_WAKEWORD";
constexpr size_t kWindowSamples = 16000;
constexpr size_t kFeatureBytes = 13 * 49;
constexpr size_t kInferenceStrideSamples = 12 * 320;  // 240 ms; inference takes about 220 ms on this board.
constexpr int64_t kTelemetryIntervalMs = 1000;
constexpr size_t kPreRollSamples = 6400;  // 400 ms at 16 kHz.
int64_t NowMs() { return esp_timer_get_time() / 1000; }
}

static void RunAssistant() {
#ifdef CONFIG_NUCLEA_SPEAKER_ONLY_TEST
    RunSpeakerMusicTest();
    return;
#endif
#ifdef CONFIG_NUCLEA_DISPLAY_ONLY_TEST
    static RobotDisplay test_display;
    ESP_LOGW(kTag, "TESTE SOMENTE TELA: SCL=4 SDA=5 RES=6 DC=7 CS=15 BLK=3V3");
    const esp_err_t result = test_display.Start();
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Falha ao iniciar visor: %s", esp_err_to_name(result));
        return;
    }
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(8000));
        test_display.Wake();
        vTaskDelay(pdMS_TO_TICKS(8000));
        test_display.Ready();
        vTaskDelay(pdMS_TO_TICKS(CONFIG_NUCLEA_DISPLAY_IDLE_MS + 3000));
    }
#endif
    ESP_LOGI(kTag, "Iniciando wakeword Nuclea no ESP32-S3");

    StatusLed led;
    const esp_err_t led_result = led.Init();
    if (led_result == ESP_OK) led.RunSelfTest();
    else ESP_LOGW(kTag, "LED RGB indisponivel: %s", esp_err_to_name(led_result));

    static WifiStation wifi;
    static AudioCapture capture;
    static AudioRecorder recorder;
    static AudioUploadWorker upload_worker;
    static RobotDisplay display;
    MFCC mfcc;
    WakewordDetector detector;
    if (recorder.Init() != ESP_OK || !mfcc.init() ||
        detector.Init() != ESP_OK) {
        ESP_LOGE(kTag, "Falha ao iniciar audio, DSP ou modelo");
        return;
    }

    if (!verify_mfcc_parity(detector.InputScale(), detector.InputZeroPoint())) {
        ESP_LOGE(kTag, "Paridade MFCC falhou; inferencia bloqueada");
        return;
    }
    const esp_err_t display_result = display.Start();
    if (display_result != ESP_OK)
        ESP_LOGW(kTag, "Visor indisponivel; continuando sem animacoes: %s", esp_err_to_name(display_result));
    if (wifi.Connect() != ESP_OK || upload_worker.Init() != ESP_OK || capture.Init() != ESP_OK) {
        ESP_LOGE(kTag, "Falha ao iniciar rede, envio ou captura");
        if (led_result == ESP_OK) led.SetError();
        return;
    }
    // Audio capture has priority 6; inference must also outrank the visual task.
    vTaskPrioritySet(nullptr, 4);
    DetectionGate gate;
    static int16_t audio_window[kWindowSamples] = {};
    static int8_t features[kFeatureBytes] = {};
    int16_t chunk[320];
    size_t filled = 0;
    size_t samples_since_inference = 0;
    int64_t last_telemetry = 0;
    float max_score_since_telemetry = 0.0f;
    uint32_t inferences_since_telemetry = 0;
    uint32_t last_sequence = 0;
    uint32_t last_loss_epoch = 0;
    int64_t led_clear_at = 0;
    int64_t playback_cooldown_until = 0;
    int64_t recording_start_at = 0;
    bool was_playing = false;
    bool restart_pending = false;

    while (true) {
        RecordingCue completed_cue;
        esp_err_t cue_result;
        if (upload_worker.PollCue(&completed_cue, &cue_result)) {
            if (cue_result != ESP_OK)
                ESP_LOGW(kTag, "Efeito de gravacao indisponivel: %s", esp_err_to_name(cue_result));
            if (completed_cue == RecordingCue::kOn) {
                // Drain the effect and its short room tail before opening the command WAV.
                recording_start_at = NowMs() + 150;
            } else {
                playback_cooldown_until = NowMs() + 150;
            }
        }
        esp_err_t completed_upload;
        if (upload_worker.Poll(&completed_upload)) {
            // The HTTP worker no longer owns this recording buffer.
            recorder.Reset();
            filled = samples_since_inference = 0;
            gate.ResetConfirmation();
            if (restart_pending) {
                restart_pending = false;
                playback_cooldown_until = 0;
                recording_start_at = NowMs() + 150;
#ifdef CONFIG_NUCLEA_RECORDING_SFX_ENABLED
                if (upload_worker.StartCue(RecordingCue::kOn) == ESP_OK)
                    recording_start_at = 0;
#endif
                display.Wake();
                led_clear_at = 0;
                if (led_result == ESP_OK) led.SetUploading();
                ESP_LOGI(kTag, "Requisicao anterior liberada; ouvindo novo comando apos onsfx");
            } else {
                display.Ready();
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
                // Only natural completion needs the longer room-echo cooldown.
                playback_cooldown_until = NowMs() + 2000;
#endif
                if (led_result == ESP_OK) {
                    if (completed_upload == ESP_OK) led.SetSuccess();
                    else led.SetError();
                    led_clear_at = NowMs() + 700;
                }
            }
        }
        if (led_clear_at != 0 && NowMs() >= led_clear_at) {
            led.SetOff();
            led_clear_at = 0;
        }
        const bool playing = upload_worker.Playing();
        if (playing != was_playing && upload_worker.Busy() && led_result == ESP_OK) {
            if (playing) led.SetSuccess();
            else led.SetUploading();
        }
        was_playing = playing;
        size_t samples_read = 0;
        if (capture.ReadPcm16(chunk, sizeof(chunk) / sizeof(chunk[0]), &samples_read) != ESP_OK || samples_read == 0) continue;
        const bool gap = (last_sequence != 0 && capture.LastSequence() - last_sequence != 1) ||
                         capture.LastLossEpoch() != last_loss_epoch;
        last_sequence = capture.LastSequence();
        last_loss_epoch = capture.LastLossEpoch();
        if (gap) {
            filled = samples_since_inference = 0;
            gate.ResetConfirmation();
            if (recorder.IsRecording()) {
                ESP_LOGE(kTag, "Gravacao descartada: lacuna na captura de audio");
                recorder.Reset();
                display.Ready();
#ifdef CONFIG_NUCLEA_RECORDING_SFX_ENABLED
                if (!upload_worker.Busy()) upload_worker.StartCue(RecordingCue::kOff);
#endif
                if (led_result == ESP_OK) led.SetError();
            }
        }
        // Keep inference active during HTTP/TTS, but never overwrite the worker's PCM.
        if (upload_worker.Busy() && !upload_worker.Interruptible()) continue;
        if (NowMs() < playback_cooldown_until) continue;

        if (recording_start_at != 0) {
            if (capture.LastTimestampMs() < recording_start_at) continue;
            recording_start_at = 0;
            filled = samples_since_inference = 0;
            // No pre-roll here: the previous window belongs to the wakeword, before onsfx.
            if (recorder.Start(chunk, 0, capture.LastTimestampMs()) != ESP_OK) {
                ESP_LOGE(kTag, "Nao foi possivel iniciar gravacao apos onsfx");
                display.Ready();
                if (led_result == ESP_OK) led.SetError();
                continue;
            }
            led_clear_at = 0;
            if (led_result == ESP_OK) led.SetRecording();
            ESP_LOGI(kTag, "Gravacao iniciada apos onsfx");
        }

        if (recorder.IsRecording()) {
            const int64_t now = capture.LastTimestampMs();
            const RecordingResult recording_result =
                recorder.Append(chunk, samples_read, capture.LastLevel().rms_dbfs, now);
            if (recording_result != RecordingResult::kContinue) {
                ESP_LOGI(kTag, "Gravacao encerrada: %u amostras, motivo=%d",
                         static_cast<unsigned>(recorder.SampleCount()),
                         static_cast<int>(recording_result));
                if (led_result == ESP_OK) led.SetUploading();
                // Empty URL still schedules offsfx locally, then reports unavailable Wi-Fi.
                const esp_err_t upload_result = upload_worker.Start(
                    recorder.Data(), recorder.SampleCount(),
                    wifi.IsConnected() ? wifi.InterfaceUrl() : std::string{}, wifi.AuthKey());
                if (upload_result != ESP_OK) {
                    ESP_LOGE(kTag, "Nao foi possivel agendar o envio: %s", esp_err_to_name(upload_result));
                    recorder.Reset();
                    display.Ready();
                    if (led_result == ESP_OK) { led.SetError(); led_clear_at = NowMs() + 700; }
                }
                filled = 0;
                samples_since_inference = 0;
            }
            continue;
        }

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
            gate.ResetConfirmation();
            ESP_LOGW(kTag, "Wakeword detectada: score=%.3f", static_cast<double>(score));
            if (upload_worker.Busy()) {
                upload_worker.Cancel();
                restart_pending = true;
                filled = samples_since_inference = 0;
                recording_start_at = 0;
                ESP_LOGW(kTag, "Interrompendo requisicao/resposta anterior por nova wakeword");
                continue;
            }
            bool cue_scheduled = false;
#ifdef CONFIG_NUCLEA_RECORDING_SFX_ENABLED
            cue_scheduled = upload_worker.StartCue(RecordingCue::kOn) == ESP_OK;
            if (cue_scheduled) {
                display.Wake();
                led_clear_at = 0;
                if (led_result == ESP_OK) led.SetUploading();
            } else {
                ESP_LOGW(kTag, "Nao foi possivel agendar onsfx; gravando sem efeito");
            }
#endif
            if (!cue_scheduled) {
                if (recorder.Start(audio_window + kWindowSamples - kPreRollSamples,
                                   kPreRollSamples, capture.LastTimestampMs()) == ESP_OK) {
                    display.Wake();
                    led_clear_at = 0;
                    if (led_result == ESP_OK) led.SetRecording();
                } else {
                    ESP_LOGE(kTag, "Nao foi possivel iniciar a gravacao");
                    if (led_result == ESP_OK) led.SetError();
                }
            }
        }
        if (now - last_telemetry >= kTelemetryIntervalMs) {
            const AudioLevel level = capture.LastLevel();
            const UBaseType_t stack_words = uxTaskGetStackHighWaterMark(nullptr);
            ESP_LOGI(kTag, "audio=%.1f dBFS peak=%d score=%.3f max_score=%.3f q_in=[%d,%d] q_out=[%d,%d] inferencias=%lu duracao=%lldms positivos=%u cooldown=%lldms led=%s stack_livre=%uB captura_stack_livre=%uB",
                      static_cast<double>(level.rms_dbfs), level.peak, static_cast<double>(score),
                      static_cast<double>(max_score_since_telemetry),
                      detector.LastInputMin(), detector.LastInputMax(),
                      detector.LastBackgroundOutput(), detector.LastWakewordOutput(),
                      static_cast<unsigned long>(inferences_since_telemetry),
                      static_cast<long long>(inference_ms),
                      gate.PositiveCount(), static_cast<long long>(gate.CooldownRemainingMs(now)),
                      led.IsGreen() ? "verde" : "apagado",
                      static_cast<unsigned>(stack_words * sizeof(StackType_t)),
                      static_cast<unsigned>(capture.StackFreeBytes()));
            last_telemetry = now;
            max_score_since_telemetry = 0.0f;
            inferences_since_telemetry = 0;
        }
        vTaskDelay(1);
    }
}

extern "C" void app_main(void) {
    // I2S capture, speaker and HTTP stay on core 0; long inference must not starve them.
    const auto entry = [](void*) { RunAssistant(); vTaskDelete(nullptr); };
    if (xTaskCreatePinnedToCore(entry, "nuclea", CONFIG_ESP_MAIN_TASK_STACK_SIZE,
                              nullptr, 4, nullptr, 1) != pdPASS)
        ESP_LOGE(kTag, "Sem memoria para iniciar a tarefa Nuclea");
}
