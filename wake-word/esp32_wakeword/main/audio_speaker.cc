#include "audio_speaker.h"
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
#include <algorithm>
#include <cstring>
#include <cmath>
#include <new>
#include "device_pins.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"

esp_err_t AudioSpeaker::Init(int volume_percent) {
    if (volume_percent < 0 || volume_percent > 100) return ESP_ERR_INVALID_ARG;
    if (task_) return ESP_OK;
    volume_percent_ = volume_percent;
    dsp_ = SpeakerDsp(SpeakerDsp::MakeConfig(
        24000, CONFIG_NUCLEA_SPEAKER_HIGHPASS_HZ, volume_percent, CONFIG_NUCLEA_SPEAKER_BOOST_DB,
        CONFIG_NUCLEA_SPEAKER_LIMIT_DBFS, 80));
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    chan.dma_desc_num = 4;
    chan.dma_frame_num = 240;
    chan.auto_clear_after_cb = true;
    esp_err_t result = i2s_new_channel(&chan, &channel_, nullptr);
    if (result != ESP_OK) return result;
    i2s_std_config_t config = {};
    config.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(24000);
    config.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
    config.gpio_cfg.mclk = I2S_GPIO_UNUSED;
    config.gpio_cfg.bclk = static_cast<gpio_num_t>(DevicePins::kSpeakerBclk);
    config.gpio_cfg.ws = static_cast<gpio_num_t>(DevicePins::kSpeakerWs);
    config.gpio_cfg.dout = static_cast<gpio_num_t>(DevicePins::kSpeakerData);
    config.gpio_cfg.din = I2S_GPIO_UNUSED;
    result = i2s_channel_init_std_mode(channel_, &config);
    if (result == ESP_OK) {
        queue_storage_ = static_cast<uint8_t*>(heap_caps_malloc(kFrames * sizeof(Frame), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        frame_ = static_cast<Frame*>(heap_caps_malloc(sizeof(Frame), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        coalescer_ = new (std::nothrow) PcmCoalescer;
        stereo_ = static_cast<int16_t*>(heap_caps_calloc(480, sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        done_ = xSemaphoreCreateBinary();
        if (!queue_storage_ || !frame_ || !coalescer_ || !stereo_ || !done_) result = ESP_ERR_NO_MEM;
    }
    if (result == ESP_OK) {
        frames_ = xQueueCreateStatic(kFrames, sizeof(Frame), queue_storage_, &queue_control_);
        if (!frames_ || xTaskCreatePinnedToCore(Entry, "speaker_tx", 4096, this, 3, &task_, 0) != pdPASS)
            result = ESP_ERR_NO_MEM;
    }
    if (result != ESP_OK) {
        if (frames_) vQueueDelete(frames_);
        if (done_) vSemaphoreDelete(done_);
        heap_caps_free(queue_storage_);
        heap_caps_free(frame_);
        delete coalescer_;
        heap_caps_free(stereo_);
        i2s_del_channel(channel_);
        frames_ = nullptr; done_ = nullptr; channel_ = nullptr;
        queue_storage_ = nullptr; frame_ = nullptr; coalescer_ = nullptr; stereo_ = nullptr;
        return result;
    }
    ESP_LOGI("SPEAKER", "I2S1 TX BCLK=%d WS=%d DIN=%d volume=%d%% boost=%d dB highpass=%d Hz limit=%d dBFS, PCM queue=%u bytes",
             DevicePins::kSpeakerBclk, DevicePins::kSpeakerWs, DevicePins::kSpeakerData,
             volume_percent_, CONFIG_NUCLEA_SPEAKER_BOOST_DB, CONFIG_NUCLEA_SPEAKER_HIGHPASS_HZ,
             CONFIG_NUCLEA_SPEAKER_LIMIT_DBFS, unsigned(kFrames * sizeof(Frame)));
    return ESP_OK;
}

esp_err_t AudioSpeaker::Begin() {
    if (session_ && Abort() != ESP_OK) return ESP_ERR_INVALID_STATE;
    if (!task_ || !idle_.load()) return ESP_ERR_INVALID_STATE;
    xQueueReset(frames_);
    coalescer_->Reset();
    queued_bytes_ = 0;
    abort_ = false; eof_ = false; failed_ = false; idle_ = false;
    session_ = true;
    xTaskNotifyGive(task_);
    return ESP_OK;
}

bool AudioSpeaker::Push(const uint8_t* pcm, size_t bytes) {
    if (!session_ || !pcm || !bytes || bytes % 2 || eof_ || idle_ || failed_ || abort_) return false;
    const int64_t deadline = esp_timer_get_time() + 6000000;
    return coalescer_->Feed(pcm, bytes, [this, deadline](const Frame& frame) {
        return Enqueue(frame, deadline);
    });
}

bool AudioSpeaker::Enqueue(const Frame& frame, int64_t deadline) {
    queued_bytes_.fetch_add(frame.bytes);
    while (xQueueSend(frames_, &frame, pdMS_TO_TICKS(20)) != pdTRUE) {
        if (idle_ || failed_ || abort_ || esp_timer_get_time() >= deadline) {
            queued_bytes_.fetch_sub(frame.bytes);
            return false;
        }
    }
    return !failed_ && !abort_ && !idle_;
}

esp_err_t AudioSpeaker::Finish() {
    if (!session_) return ESP_ERR_INVALID_STATE;
    const int64_t deadline = esp_timer_get_time() + 6000000;
    if (!coalescer_->Flush([this, deadline](const Frame& frame) { return Enqueue(frame, deadline); })) {
        Abort();
        return ESP_FAIL;
    }
    eof_ = true;
    if (xSemaphoreTake(done_, pdMS_TO_TICKS(8000)) != pdTRUE) {
        Abort();
        return ESP_ERR_TIMEOUT;
    }
    session_ = false;
    return failed_ ? ESP_FAIL : ESP_OK;
}

esp_err_t AudioSpeaker::Abort() {
    if (!session_) return ESP_OK;
    abort_ = true;
    if (xSemaphoreTake(done_, pdMS_TO_TICKS(2000)) != pdTRUE) return ESP_ERR_TIMEOUT;
    coalescer_->Reset();
    session_ = false;
    return ESP_OK;
}

bool AudioSpeaker::Write(const void* data, size_t bytes) {
    size_t written = 0;
    const esp_err_t result = i2s_channel_write(channel_, data, bytes, &written, 100);
    if (result != ESP_OK || written != bytes) {
        ESP_LOGE("SPEAKER", "I2S write failed: %s, bytes=%u/%u",
                 esp_err_to_name(result), unsigned(written), unsigned(bytes));
        return false;
    }
    return true;
}

void AudioSpeaker::Entry(void* context) { static_cast<AudioSpeaker*>(context)->Run(); }

void AudioSpeaker::Run() {
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        bool enabled = false;
        bool buffering = true;
        size_t pcm_bytes_written = 0;
        int peak_input = 0;
        int peak_output = 0;
        uint64_t input_square_sum = 0;
        size_t input_samples = 0;
        size_t clipped_samples = 0;
        unsigned rebuffer_count = 0;
        int64_t last_pcm = esp_timer_get_time();
        dsp_.Reset();
        while (!abort_ && !failed_) {
            // Observe producer EOF before inspecting the queue so the final enqueue is visible.
            const bool ended = eof_.load();
            const UBaseType_t queued = uxQueueMessagesWaiting(frames_);
            if (ended && queued == 0) break;
            if (buffering && !ended && queued_bytes_.load() < 48000) {
                if (esp_timer_get_time() - last_pcm > 220000000) { failed_ = true; break; }
                vTaskDelay(pdMS_TO_TICKS(10));
                continue;
            }
            if (xQueueReceive(frames_, frame_, pdMS_TO_TICKS(20)) != pdTRUE) {
                if (!buffering) ++rebuffer_count;
                buffering = true;
                playing_ = false;
                continue;
            }
            queued_bytes_.fetch_sub(frame_->bytes);
            if (!enabled) {
                // Overwrite every DMA descriptor before enabling, including after an abort.
                std::memset(stereo_, 0, 960);
                for (int i = 0; i < 4; ++i) {
                    size_t loaded = 0;
                    const esp_err_t preload = i2s_channel_preload_data(channel_, stereo_, 960, &loaded);
                    if (preload != ESP_OK || loaded != 960) {
                        ESP_LOGE("SPEAKER", "DMA preload failed: %s, bytes=%u/960",
                                 esp_err_to_name(preload), unsigned(loaded));
                        failed_ = true; break;
                    }
                }
                if (failed_) break;
                const esp_err_t started = i2s_channel_enable(channel_);
                if (started != ESP_OK) {
                    ESP_LOGE("SPEAKER", "I2S enable failed: %s", esp_err_to_name(started));
                    failed_ = true; break;
                }
                enabled = true;
                ESP_LOGI("SPEAKER", "Playback started: PCM16 mono 24000 Hz -> I2S stereo, volume=%d%%",
                         volume_percent_);
            }
            buffering = false;
            playing_ = true;
            for (size_t i = 0; i < frame_->bytes / 2; ++i) {
                const uint16_t raw = frame_->pcm[i * 2] | (uint16_t(frame_->pcm[i * 2 + 1]) << 8);
                const int32_t signed_sample = raw < 32768 ? raw : int32_t(raw) - 65536;
                const int16_t sample = dsp_.Process(static_cast<int16_t>(signed_sample));
                input_square_sum += static_cast<int64_t>(signed_sample) * signed_sample;
                ++input_samples;
                if (signed_sample >= 32760 || signed_sample <= -32760) ++clipped_samples;
                peak_input = std::max(peak_input, int(signed_sample < 0 ? -signed_sample : signed_sample));
                peak_output = std::max(peak_output, int(sample < 0 ? -int(sample) : int(sample)));
                stereo_[i * 2] = stereo_[i * 2 + 1] = sample;
            }
            if (!Write(stereo_, frame_->bytes * 2)) failed_ = true;
            else pcm_bytes_written += frame_->bytes;
            last_pcm = esp_timer_get_time();
        }
        if (enabled) {
            if (!abort_ && !failed_) {
                std::memset(stereo_, 0, 960);
                // write() queues DMA; a full ring of silence plus its duration drains the tail.
                for (int i = 0; i < 4 && !abort_; ++i)
                    if (!Write(stereo_, 960)) failed_ = true;
                vTaskDelay(pdMS_TO_TICKS(50));
            }
            if (i2s_channel_disable(channel_) != ESP_OK) failed_ = true;
        }
        playing_ = false;
        const double rms_dbfs = input_samples && input_square_sum
            ? 10.0 * std::log10(static_cast<double>(input_square_sum) / input_samples / 1073741824.0)
            : -120.0;
        // clipped counts source samples already at full scale (clipped before the ESP).
        ESP_LOGI("SPEAKER", "Playback ended: PCM_bytes=%u peak_in=%d peak_out=%d rms_in=%.1f dBFS clipped=%u limiter=%.1f dB rebuffer=%u failed=%d aborted=%d",
                 unsigned(pcm_bytes_written), peak_input, peak_output,
                 rms_dbfs, unsigned(clipped_samples), 20.0 * std::log10(dsp_.MinGain()), rebuffer_count,
                 int(failed_.load()), int(abort_.load()));
        xQueueReset(frames_);
        idle_ = true;
        xSemaphoreGive(done_);
    }
}
#endif
