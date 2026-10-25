#include "audio_uploader.h"
#include "auth_key.h"

#include <array>
#include <algorithm>
#include <cstring>
#include <cstdio>
#include <cerrno>
#include <string>
#include <strings.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "speaker_response.h"
#include "http_read_budget.h"
#include "sdkconfig.h"

namespace {
constexpr const char* kTag = "AUDIO_UPLOADER";
constexpr const char* kBoundary = "----NucleaEsp32Boundary";

struct ResponseHeaders {
    UploadCancellation* cancellation = nullptr;
    char mime[96] = {};
    char encoding[32] = {};
    char request_id[65] = {};
    HttpReadBudget budget{0, 0};
    bool reading_body = false;
    bool expired = false;
};

void RefreshReadTimeout(esp_http_client_handle_t client, ResponseHeaders& context) {
    if (!context.reading_body) return;
    const int64_t now = esp_timer_get_time();
    context.expired = context.expired || context.budget.Expired(now);
    esp_http_client_set_timeout_ms(client, context.expired ? 1 : context.budget.TimeoutMs(now));
}

esp_err_t OnHttpEvent(esp_http_client_event_t* event) {
    auto* headers = static_cast<ResponseHeaders*>(event->user_data);
    if (headers->cancellation) {
        if (event->event_id == HTTP_EVENT_ON_CONNECTED)
            headers->cancellation->PublishSocket(esp_http_client_get_socket(event->client));
        if (event->event_id == HTTP_EVENT_DISCONNECTED)
            headers->cancellation->DetachSocket();
    }
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key &&
        strcasecmp(event->header_key, "Content-Type") == 0) {
        std::snprintf(headers->mime, sizeof(headers->mime), "%s", event->header_value);
    }
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value) {
        if (strcasecmp(event->header_key, "Content-Encoding") == 0)
            std::snprintf(headers->encoding, sizeof(headers->encoding), "%s", event->header_value);
        if (strcasecmp(event->header_key, "X-Request-ID") == 0)
            std::snprintf(headers->request_id, sizeof(headers->request_id), "%s", event->header_value);
    }
    // read() may issue many transport reads. This callback runs on the same owner
    // thread, shrinking the timeout for the next internal read without closing it.
    if (event->event_id == HTTP_EVENT_ON_DATA) RefreshReadTimeout(event->client, *headers);
    return ESP_OK;
}
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
bool NdjsonMime(const char* mime) {
    constexpr const char* expected = "application/x-ndjson";
    const size_t length = std::strlen(expected);
    return strncasecmp(mime, expected, length) == 0 &&
           (mime[length] == '\0' || mime[length] == ';' || mime[length] == ' ');
}

esp_err_t PlayResponse(esp_http_client_handle_t client, AudioSpeaker& speaker, int64_t deadline,
                       ResponseHeaders& context, std::atomic<bool>* response_started) {
    const auto cancelled = [&context] {
        return context.cancellation && context.cancellation->Cancelled();
    };
    if (cancelled()) return ESP_ERR_INVALID_STATE;
    SpeakerResponse response(speaker);
    if (!response.Ready()) return ESP_ERR_NO_MEM;
    esp_err_t result = speaker.Begin();
    if (result != ESP_OK) return result;
    if (cancelled()) { speaker.Abort(); return ESP_ERR_INVALID_STATE; }
    context.budget = HttpReadBudget(deadline, esp_timer_get_time());
    context.expired = false;
    context.reading_body = true;
    char chunk[1024];
    size_t received_bytes = 0;
    while (result == ESP_OK) {
        if (cancelled()) { result = ESP_ERR_INVALID_STATE; break; }
        RefreshReadTimeout(client, context);
        if (context.expired) { result = ESP_ERR_TIMEOUT; break; }
        const int count = esp_http_client_read(client, chunk, sizeof(chunk));
        const int read_errno = errno;
        if (cancelled()) { result = ESP_ERR_INVALID_STATE; break; }
        RefreshReadTimeout(client, context);
        // Never parse or enqueue late data, even when read() returned positive bytes.
        if (context.expired) { result = ESP_ERR_TIMEOUT; break; }
        if (count == -ESP_ERR_HTTP_EAGAIN) continue;
        if (count < 0) {
            ESP_LOGE(kTag, "Stream transport failed: read=%d errno=%d received=%u audio_events=%u",
                     count, read_errno, unsigned(received_bytes), unsigned(response.AudioEvents()));
            result = ESP_FAIL; break;
        }
        if (count == 0) {
            if (!esp_http_client_is_complete_data_received(client) || !response.Complete()) {
                ESP_LOGE(kTag, "Stream ended early: HTTP_complete=%d NDJSON_complete=%d received=%u audio_events=%u partial_line=%u",
                         int(esp_http_client_is_complete_data_received(client)), int(response.Complete()),
                         unsigned(received_bytes), unsigned(response.AudioEvents()), unsigned(response.BufferedBytes()));
                result = ESP_FAIL;
            }
            break;
        }
        received_bytes += static_cast<size_t>(count);
        const size_t before = response.AudioEvents();
        if (!response.Feed(chunk, count)) {
            ESP_LOGE(kTag, "Stream rejected: framing=%s received=%u audio_events=%u partial_line=%u",
                     response.FramingError(), unsigned(received_bytes), unsigned(response.AudioEvents()),
                     unsigned(response.BufferedBytes()));
            result = ESP_FAIL;
        }
        RefreshReadTimeout(client, context);
        if (context.expired) result = ESP_ERR_TIMEOUT;
        if (result == ESP_OK && response.AudioEvents() != before) {
            context.budget.AudioProgress(esp_timer_get_time());
            if (before == 0 && response_started && !cancelled()) response_started->store(true);
        }
    }
    context.reading_body = false;
    if (result == ESP_OK) result = speaker.Finish();
    if (cancelled()) result = ESP_ERR_INVALID_STATE;
    if (result != ESP_OK) {
        const esp_err_t stopped = speaker.Abort();
        if (!cancelled())
            ESP_LOGE(kTag, "Speaker response failed: %s; stop=%s request_id=%.64s",
                     esp_err_to_name(result), esp_err_to_name(stopped), context.request_id);
    }
    return result;
}
#endif

void PutLe16(uint8_t* target, uint16_t value) {
    target[0] = value & 0xff;
    target[1] = (value >> 8) & 0xff;
}

void PutLe32(uint8_t* target, uint32_t value) {
    target[0] = value & 0xff;
    target[1] = (value >> 8) & 0xff;
    target[2] = (value >> 16) & 0xff;
    target[3] = (value >> 24) & 0xff;
}

std::array<uint8_t, 44> WavHeader(size_t sample_count) {
    std::array<uint8_t, 44> header = {};
    const uint32_t data_bytes = static_cast<uint32_t>(sample_count * sizeof(int16_t));
    std::memcpy(header.data(), "RIFF", 4);
    PutLe32(header.data() + 4, 36 + data_bytes);
    std::memcpy(header.data() + 8, "WAVEfmt ", 8);
    PutLe32(header.data() + 16, 16);
    PutLe16(header.data() + 20, 1);
    PutLe16(header.data() + 22, 1);
    PutLe32(header.data() + 24, 16000);
    PutLe32(header.data() + 28, 16000 * sizeof(int16_t));
    PutLe16(header.data() + 32, sizeof(int16_t));
    PutLe16(header.data() + 34, 16);
    std::memcpy(header.data() + 36, "data", 4);
    PutLe32(header.data() + 40, data_bytes);
    return header;
}

bool SetRequestBudget(esp_http_client_handle_t client, int64_t deadline) {
    const int64_t remaining_ms = (deadline - esp_timer_get_time()) / 1000;
    if (remaining_ms <= 0) return false;
    return esp_http_client_set_timeout_ms(client, static_cast<int>(std::min<int64_t>(220000, remaining_ms))) == ESP_OK;
}

bool WriteAll(esp_http_client_handle_t client, const void* data, size_t size, int64_t deadline,
              UploadCancellation* cancellation) {
    const char* cursor = static_cast<const char*>(data);
    while (size > 0) {
        if ((cancellation && cancellation->Cancelled()) || !SetRequestBudget(client, deadline)) return false;
        const int written = esp_http_client_write(client, cursor, static_cast<int>(std::min<size_t>(size, 4096)));
        if (written <= 0) return false;
        cursor += written;
        size -= static_cast<size_t>(written);
    }
    return true;
}
}

esp_err_t AudioUploader::Upload(const int16_t* samples, size_t sample_count,
                                const std::string& base_url, AudioSpeaker* speaker,
                                const std::string& auth_key, UploadCancellation* cancellation,
                                std::atomic<bool>* response_started) const {
    if (samples == nullptr || sample_count == 0 || base_url.empty()) return ESP_ERR_INVALID_ARG;
    if (cancellation && cancellation->Cancelled()) return ESP_ERR_INVALID_STATE;
    if (!auth_key.empty() && (!ValidAuthKey(auth_key) || base_url.compare(0, 8, "https://") != 0)) {
        ESP_LOGE(kTag, "Chave invalida ou gateway sem HTTPS; envio bloqueado");
        return ESP_ERR_INVALID_ARG;
    }

    std::string url = base_url;
    while (!url.empty() && url.back() == '/') url.pop_back();
    url += "/api/device-audio";

#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
    if (!speaker) return ESP_ERR_INVALID_STATE;
    ESP_LOGI(kTag, "Response mode=speaker; expecting PCM NDJSON on this POST");
    const std::string mode = std::string("--") + kBoundary +
        "\r\nContent-Disposition: form-data; name=\"responseMode\"\r\n\r\nspeaker\r\n";
#else
    (void)speaker;
    (void)response_started;
    const std::string mode;
#endif
    char prefix[768];
    const int prefix_length = std::snprintf(
        prefix, sizeof(prefix),
        "%s--%s\r\nContent-Disposition: form-data; name=\"deviceId\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"command.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n",
        mode.c_str(), kBoundary, CONFIG_NUCLEA_DEVICE_ID, kBoundary);
    if (prefix_length <= 0 || prefix_length >= static_cast<int>(sizeof(prefix))) return ESP_ERR_INVALID_SIZE;

    const std::string suffix = std::string("\r\n--") + kBoundary + "--\r\n";
    const auto wav_header = WavHeader(sample_count);
    const size_t pcm_bytes = sample_count * sizeof(int16_t);
    const size_t content_length = static_cast<size_t>(prefix_length) + wav_header.size() +
                                  pcm_bytes + suffix.size();

    esp_http_client_config_t config = {};
    config.url = url.c_str();
    // Bound DNS/TLS establishment too; a connected request is interrupted through shutdown().
    config.timeout_ms = 5000;
    config.disable_auto_redirect = true;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    ResponseHeaders headers;
    headers.cancellation = cancellation;
    config.event_handler = OnHttpEvent;
    config.user_data = &headers;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) return ESP_ERR_NO_MEM;

    const std::string content_type = std::string("multipart/form-data; boundary=") + kBoundary;
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", content_type.c_str());
    if (!auth_key.empty() && esp_http_client_set_header(client, "X-Nuclea-Key", auth_key.c_str()) != ESP_OK) {
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }
    // The MCU consumes raw NDJSON; it has no HTTP gzip/brotli decompressor.
    esp_http_client_set_header(client, "Accept-Encoding", "identity");
    esp_http_client_set_header(client, "Accept", "application/x-ndjson");

    const int64_t deadline = esp_timer_get_time() + 240000000;
    esp_err_t result = esp_http_client_open(client, static_cast<int>(content_length));
    if (result == ESP_OK &&
        (!WriteAll(client, prefix, static_cast<size_t>(prefix_length), deadline, cancellation) ||
         !WriteAll(client, wav_header.data(), wav_header.size(), deadline, cancellation) ||
         !WriteAll(client, samples, pcm_bytes, deadline, cancellation) ||
         !WriteAll(client, suffix.data(), suffix.size(), deadline, cancellation))) {
        result = ESP_FAIL;
    }

    if (cancellation && cancellation->Cancelled()) result = ESP_ERR_INVALID_STATE;
    if (result == ESP_OK && !SetRequestBudget(client, deadline)) result = ESP_ERR_TIMEOUT;
    if (result == ESP_OK && esp_http_client_fetch_headers(client) < 0) result = ESP_FAIL;
    if (cancellation && cancellation->Cancelled()) result = ESP_ERR_INVALID_STATE;
    const int status = result == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    ESP_LOGI(kTag, "Response headers: HTTP=%d MIME=%.95s encoding=%.31s request_id=%.64s",
             status, headers.mime, headers.encoding[0] ? headers.encoding : "identity", headers.request_id);
    if (status == 401 || status == 403) {
        ESP_LOGE(kTag, "Acesso recusado pelo servidor (HTTP=%d). Confira X-Nuclea-Key no portal e Header Auth no n8n; request_id=%.64s",
                 status, headers.request_id);
    }
    if (result == ESP_OK && (status < 200 || status >= 300)) result = ESP_FAIL;
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
    if (result == ESP_OK && !NdjsonMime(headers.mime)) result = ESP_ERR_INVALID_RESPONSE;
    if (result == ESP_OK && headers.encoding[0] && strcasecmp(headers.encoding, "identity") != 0) {
        ESP_LOGE(kTag, "Unsupported HTTP encoding: %s; disable compression on gateway Ingress", headers.encoding);
        result = ESP_ERR_INVALID_RESPONSE;
    }
    if (result == ESP_OK) result = PlayResponse(client, *speaker, deadline, headers, response_started);
#else
    (void)deadline;
    int discarded = 0;
    if (result == ESP_OK) result = esp_http_client_flush_response(client, &discarded);
#endif
    if (cancellation) cancellation->DetachSocket();
    esp_http_client_cleanup(client);

    if (cancellation && cancellation->Cancelled()) {
        ESP_LOGI(kTag, "Requisicao cancelada; resposta antiga descartada");
        return ESP_ERR_INVALID_STATE;
    }

    if (result != ESP_OK || status < 200 || status >= 300) {
        ESP_LOGE(kTag, "Upload falhou: err=%s HTTP=%d MIME=%.95s", esp_err_to_name(result), status, headers.mime);
        return result == ESP_OK ? ESP_FAIL : result;
    }
    ESP_LOGI(kTag, "Audio enviado: %u amostras, HTTP=%d",
             static_cast<unsigned>(sample_count), status);
    return ESP_OK;
}
