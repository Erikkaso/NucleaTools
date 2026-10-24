#include "speaker_response.h"
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
#include <cmath>
#include <cstring>
#include "cJSON.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"

namespace {
// cJSON is recursive; cap depth before parsing untrusted network input on the worker stack.
bool ShallowJson(const char* data, size_t size) {
    unsigned depth = 0;
    bool quoted = false, escaped = false;
    for (size_t i = 0; i < size; ++i) {
        const char c = data[i];
        if (quoted) {
            if (escaped) escaped = false;
            else if (c == '\\') escaped = true;
            else if (c == '"') quoted = false;
        } else if (c == '"') quoted = true;
        else if (c == '{' || c == '[') { if (++depth > 4) return false; }
        else if (c == '}' || c == ']') { if (!depth) return false; --depth; }
    }
    return !depth && !quoted;
}
const cJSON* Field(const cJSON* root, const char* key) {
    return cJSON_GetObjectItemCaseSensitive(root, key);
}
bool StringIs(const cJSON* item, const char* value) {
    return cJSON_IsString(item) && std::strcmp(item->valuestring, value) == 0;
}
bool Integer(const cJSON* item, double min, double max) {
    return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
           item->valuedouble >= min && item->valuedouble <= max &&
           std::floor(item->valuedouble) == item->valuedouble;
}
bool Base64(const char* text, size_t length) {
    if (!length || length > 6400 || length % 4) return false;
    size_t padding = 0;
    for (size_t i = 0; i < length; ++i) {
        const unsigned char c = text[i];
        if (c == '=') { if (++padding > 2 || i < length - 2) return false; }
        else if (padding || !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                             (c >= '0' && c <= '9') || c == '+' || c == '/')) return false;
    }
    return true;
}
}

SpeakerResponse::SpeakerResponse(AudioSpeaker& speaker)
    : speaker_(speaker),
      line_(static_cast<char*>(heap_caps_malloc(8192, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT))),
      pcm_(static_cast<uint8_t*>(heap_caps_malloc(4800, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT))),
      framer_(line_, 8192) {
    if (!Ready())
        ESP_LOGE("SPEAKER_STREAM", "PSRAM stream buffers unavailable: free=%u",
                 unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
}
SpeakerResponse::~SpeakerResponse() { heap_caps_free(pcm_); heap_caps_free(line_); }
bool SpeakerResponse::Feed(const char* data, size_t size) {
    return Ready() && framer_.Feed(data, size, [this](const char* line, size_t length) {
        return Line(line, length);
    });
}
bool SpeakerResponse::Line(const char* data, size_t size) {
    if (!ShallowJson(data, size) || std::strstr(data, "\\u0000")) {
        ESP_LOGE("SPEAKER_STREAM", "JSON envelope rejected: bytes=%u expected_seq=%u",
                 unsigned(size), unsigned(audio_events_));
        return false;
    }
    const char* parse_end = nullptr;
    cJSON* root = cJSON_ParseWithLengthOpts(data, size + 1, &parse_end, true);
    if (!root) {
        const int offset = parse_end ? static_cast<int>(parse_end - data) : -1;
        ESP_LOGE("SPEAKER_STREAM", "JSON parse failed: bytes=%u offset=%d expected_seq=%u internal_free=%u internal_largest=%u psram_free=%u",
                 unsigned(size), offset, unsigned(audio_events_),
                 unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
                 unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
                 unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
        return false;
    }
    const char* stage = "object_or_duplicate_fields";
    const size_t expected_seq = audio_events_;
    bool valid = cJSON_IsObject(root);
    // Reject ambiguous duplicate fields rather than silently selecting the first.
    for (const cJSON* a = root->child; a && valid; a = a->next)
        for (const cJSON* b = a->next; b; b = b->next)
            if (!a->string || !b->string || std::strcmp(a->string, b->string) == 0) { valid = false; break; }
    const cJSON* type = Field(root, "type");
    if (valid && StringIs(type, "start")) {
        stage = "start_format_or_state";
        valid = StringIs(Field(root, "format"), "pcm_s16le") &&
                Integer(Field(root, "channels"), 1, 1) && state_.Start();
    } else if (valid && StringIs(type, "audio")) {
        stage = "audio_metadata";
        const cJSON* seq = Field(root, "seq");
        const cJSON* rate = Field(root, "sample_rate");
        const cJSON* encoded = Field(root, "data");
        valid = Integer(seq, 0, UINT32_MAX - 1) && Integer(rate, 24000, 24000) && cJSON_IsString(encoded);
        size_t decoded = 0;
        if (valid) {
            stage = "audio_base64";
            const size_t length = std::strlen(encoded->valuestring);
            valid = Base64(encoded->valuestring, length) &&
                    mbedtls_base64_decode(pcm_, 4800, &decoded,
                        reinterpret_cast<const unsigned char*>(encoded->valuestring), length) == 0;
        }
        if (valid) {
            stage = "audio_sequence_or_size";
            valid = state_.Audio(static_cast<uint32_t>(seq->valuedouble), 24000, decoded);
        }
        if (valid) {
            stage = "speaker_queue";
            valid = speaker_.Push(pcm_, decoded);
        }
        if (valid) {
            if (audio_events_ == 0)
                ESP_LOGI("SPEAKER_STREAM", "First PCM packet accepted: %u bytes, 24000 Hz", unsigned(decoded));
            ++audio_events_;
        }
    } else if (valid && StringIs(type, "ping")) {
        stage = "ping_state";
        valid = state_.Ping();
    } else if (valid && StringIs(type, "end")) {
        stage = "end_state";
        valid = state_.End();
    }
    else {
        stage = "unknown_or_server_error";
        if (StringIs(type, "error")) {
            const cJSON* message = Field(root, "message");
            const cJSON* code = Field(root, "code");
            ESP_LOGE("SPEAKER_STREAM", "Server error code=%.64s: %.160s",
                     cJSON_IsString(code) ? code->valuestring : "unspecified",
                     cJSON_IsString(message) ? message->valuestring : "missing message");
        }
        valid = false;
    }
    if (!valid) {
        const cJSON* seq = Field(root, "seq");
        const cJSON* rate = Field(root, "sample_rate");
        ESP_LOGE("SPEAKER_STREAM", "Rejected event stage=%s type=%.16s seq=%.0f expected_seq=%u rate=%.0f bytes=%u",
                 stage, cJSON_IsString(type) ? type->valuestring : "missing",
                 Integer(seq, 0, UINT32_MAX) ? seq->valuedouble : -1.0, unsigned(expected_seq),
                 Integer(rate, 0, 192000) ? rate->valuedouble : -1.0, unsigned(size));
    }
    cJSON_Delete(root);
    return valid;
}
#endif
