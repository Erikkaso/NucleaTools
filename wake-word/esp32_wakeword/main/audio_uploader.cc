#include "audio_uploader.h"

#include <array>
#include <cstring>
#include <cstdio>
#include <string>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "sdkconfig.h"

namespace {
constexpr const char* kTag = "AUDIO_UPLOADER";
constexpr const char* kBoundary = "----NucleaEsp32Boundary";

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

bool WriteAll(esp_http_client_handle_t client, const void* data, size_t size) {
    const char* cursor = static_cast<const char*>(data);
    while (size > 0) {
        const int written = esp_http_client_write(client, cursor, static_cast<int>(size));
        if (written <= 0) return false;
        cursor += written;
        size -= static_cast<size_t>(written);
    }
    return true;
}
}

esp_err_t AudioUploader::Upload(const int16_t* samples, size_t sample_count,
                                const std::string& base_url) const {
    if (samples == nullptr || sample_count == 0 || base_url.empty()) return ESP_ERR_INVALID_ARG;

    std::string url = base_url;
    while (!url.empty() && url.back() == '/') url.pop_back();
    url += "/api/device-audio";

    char prefix[512];
    const int prefix_length = std::snprintf(
        prefix, sizeof(prefix),
        "--%s\r\nContent-Disposition: form-data; name=\"deviceId\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"command.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n",
        kBoundary, CONFIG_NUCLEA_DEVICE_ID, kBoundary);
    if (prefix_length <= 0 || prefix_length >= static_cast<int>(sizeof(prefix))) return ESP_ERR_INVALID_SIZE;

    const std::string suffix = std::string("\r\n--") + kBoundary + "--\r\n";
    const auto wav_header = WavHeader(sample_count);
    const size_t pcm_bytes = sample_count * sizeof(int16_t);
    const size_t content_length = static_cast<size_t>(prefix_length) + wav_header.size() +
                                  pcm_bytes + suffix.size();

    esp_http_client_config_t config = {};
    config.url = url.c_str();
    config.timeout_ms = 120000;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) return ESP_ERR_NO_MEM;

    const std::string content_type = std::string("multipart/form-data; boundary=") + kBoundary;
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", content_type.c_str());

    esp_err_t result = esp_http_client_open(client, static_cast<int>(content_length));
    if (result == ESP_OK &&
        (!WriteAll(client, prefix, static_cast<size_t>(prefix_length)) ||
         !WriteAll(client, wav_header.data(), wav_header.size()) ||
         !WriteAll(client, samples, pcm_bytes) ||
         !WriteAll(client, suffix.data(), suffix.size()))) {
        result = ESP_FAIL;
    }

    if (result == ESP_OK && esp_http_client_fetch_headers(client) < 0) result = ESP_FAIL;
    const int status = result == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    int discarded = 0;
    if (result == ESP_OK) esp_http_client_flush_response(client, &discarded);
    esp_http_client_cleanup(client);

    if (result != ESP_OK || status < 200 || status >= 300) {
        ESP_LOGE(kTag, "Upload falhou: err=%s HTTP=%d", esp_err_to_name(result), status);
        return result == ESP_OK ? ESP_FAIL : result;
    }
    ESP_LOGI(kTag, "Audio enviado: %u amostras, HTTP=%d",
             static_cast<unsigned>(sample_count), status);
    return ESP_OK;
}
