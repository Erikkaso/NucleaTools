#include "robot_display.h"
#include <algorithm>
#include <cstring>
#include <new>
#include "device_pins.h"
#include "display_timing.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "shake_detector.h"

namespace {
constexpr const char* kTag = "ROBOT_DISPLAY";
constexpr int kStripLines = 16;
constexpr const char* kSleep = "/robot/sleep2.gif";
// wake-open2.gif goes from open to closed eyes; wake-open2-reverse.gif is its exact reverse
// (tools/reverse_gif.py), so neither transition needs a PSRAM frame cache.
constexpr const char* kWake = "/robot/wake-open2-reverse.gif";
constexpr const char* kClose = "/robot/wake-open2.gif";
constexpr const char* kAwake = "/robot/idle.gif";
constexpr const char* kSmile = "/robot/smile.gif";
constexpr const char* kElegant = "/robot/elegant.gif";
constexpr const char* kDizzy = "/robot/dizzy.gif";
constexpr const char* kAngry = "/robot/angry.gif";
constexpr const char* kCry = "/robot/cry.gif";
constexpr const char* kLoadingIn = "/robot/loadingtrans.gif";
constexpr const char* kLoading = "/robot/loading.gif";
constexpr const char* kLoadingOut = "/robot/loadingtrans-reverse.gif";
const char* ClipPath(VisualClip clip) {
    switch (clip) {
        case VisualClip::kSleep: return kSleep;
        case VisualClip::kSmile: return kSmile;
        case VisualClip::kElegant: return kElegant;
        case VisualClip::kDizzy: return kDizzy;
        case VisualClip::kAngry: return kAngry;
        case VisualClip::kCry: return kCry;
        case VisualClip::kLoadingIn: return kLoadingIn;
        case VisualClip::kLoading: return kLoading;
        case VisualClip::kLoadingOut: return kLoadingOut;
        case VisualClip::kWake: return kWake;
        case VisualClip::kClose: return kClose;
        default: return kAwake;
    }
}
int64_t NowMs() { return esp_timer_get_time() / 1000; }
}

esp_err_t RobotDisplay::Start() {
#ifndef CONFIG_NUCLEA_DISPLAY_ENABLED
    return ESP_OK;
#else
    esp_vfs_littlefs_conf_t fs = {};
    fs.base_path = "/robot";
    fs.partition_label = "spiffs";
    fs.format_if_mount_failed = false;
    ESP_RETURN_ON_ERROR(esp_vfs_littlefs_register(&fs), kTag, "LittleFS indisponivel (nao formatado)");
    void* memory = heap_caps_malloc(sizeof(GifAnimation), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!memory) return ESP_ERR_NO_MEM;
    animation_ = new (memory) GifAnimation();
    if (!animation_->Init()) return ESP_ERR_NO_MEM;
    for (const char* asset : {kSleep, kWake, kClose, kAwake}) {
        if (!animation_->Open(asset)) {
            ESP_LOGE(kTag, "GIF ausente ou invalido (esperado 280x240): %s", asset);
            return ESP_ERR_NOT_FOUND;
        }
        animation_->Close();
    }
    for (const char* asset : {kSmile, kElegant, kDizzy, kAngry, kCry, kLoadingIn, kLoading, kLoadingOut}) {
        if (!animation_->Open(asset)) ESP_LOGW(kTag, "GIF opcional indisponivel: %s; usando blink", asset);
        animation_->Close();
    }
    ESP_RETURN_ON_ERROR(InitPanel(), kTag, "ST7789 init");
    events_ = xQueueCreate(16, sizeof(Event));
    if (!events_) return ESP_ERR_NO_MEM;
    // Core 0, one above the decoder: when a DMA strip completes the LCD task preempts the
    // decoder at once (equal priorities would wait for a 10 ms tick per strip). It mostly sleeps
    // on DMA, so capture (6), speaker (3) and inference (core 1) keep their timing.
    if (xTaskCreatePinnedToCore(LcdEntry, "robot_lcd", 3072, this, 2, nullptr, 0) != pdPASS)
        return ESP_ERR_NO_MEM;
    // Keep decoding off the inference core, below capture, speaker and HTTP priorities.
    if (xTaskCreatePinnedToCore(Entry, "robot_display", 6144, this, 1, nullptr, 0) != pdPASS) {
        vQueueDelete(events_);
        events_ = nullptr;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
#endif
}

bool RobotDisplay::TransferDone(esp_lcd_panel_io_handle_t,
                               esp_lcd_panel_io_event_data_t*, void* context) {
    BaseType_t higher_priority = pdFALSE;
    xSemaphoreGiveFromISR(static_cast<RobotDisplay*>(context)->dma_done_, &higher_priority);
    return higher_priority == pdTRUE;
}

esp_err_t RobotDisplay::InitPanel() {
    dma_done_ = xSemaphoreCreateBinary();
    dma_strip_ = static_cast<uint16_t*>(heap_caps_malloc(
        GifAnimation::kWidth * kStripLines * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
    frame_copy_ = static_cast<uint16_t*>(heap_caps_malloc(GifAnimation::kFrameBytes,
                                                          MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    lcd_go_ = xSemaphoreCreateBinary();
    lcd_idle_ = xSemaphoreCreateBinary();
    if (!dma_done_ || !dma_strip_ || !frame_copy_ || !lcd_go_ || !lcd_idle_) return ESP_ERR_NO_MEM;
    xSemaphoreGive(lcd_idle_);
    spi_bus_config_t bus = {};
    bus.sclk_io_num = DevicePins::kLcdClock;
    bus.mosi_io_num = DevicePins::kLcdMosi;
    bus.miso_io_num = -1;
    bus.quadwp_io_num = bus.quadhd_io_num = -1;
    bus.max_transfer_sz = GifAnimation::kWidth * kStripLines * 2;
    ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO), kTag, "SPI init");
    esp_lcd_panel_io_spi_config_t io = {};
    io.cs_gpio_num = DevicePins::kLcdCs;
    io.dc_gpio_num = DevicePins::kLcdDc;
    io.pclk_hz = CONFIG_NUCLEA_DISPLAY_SPI_MHZ * 1000000;
    io.trans_queue_depth = 1;
    io.lcd_cmd_bits = io.lcd_param_bits = 8;
    io.on_color_trans_done = TransferDone;
    io.user_ctx = this;
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_spi(SPI2_HOST, &io, &io_), kTag, "LCD IO");
    esp_lcd_panel_dev_config_t panel = {};
    panel.reset_gpio_num = DevicePins::kLcdReset;
    panel.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
    panel.data_endian = LCD_RGB_DATA_ENDIAN_LITTLE;
    panel.bits_per_pixel = 16;
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7789(io_, &panel, &panel_), kTag, "LCD panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(panel_), kTag, "LCD reset");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(panel_), kTag, "LCD init");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_swap_xy(panel_, true), kTag, "LCD landscape");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_mirror(panel_, false, false), kTag, "LCD rotation");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_set_gap(panel_, CONFIG_NUCLEA_DISPLAY_X_GAP,
                                            CONFIG_NUCLEA_DISPLAY_Y_GAP), kTag, "LCD gap");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_invert_color(panel_, true), kTag, "LCD invert");
    return esp_lcd_panel_disp_on_off(panel_, true);
}

bool RobotDisplay::Flush(int x0, int y0, int x1, int y1) {
    const int w = x1 - x0;
    if (w <= 0 || y1 <= y0) return true;
    const int max_lines = std::max(1, kStripLines * GifAnimation::kWidth / w);
    for (int y = y0; y < y1; y += max_lines) {
        const int lines = std::min(max_lines, y1 - y);
        for (int row = 0; row < lines; ++row) {
            const uint16_t* source = frame_copy_ + (y + row) * GifAnimation::kWidth + x0;
            std::memcpy(dma_strip_ + row * w, source, w * sizeof(uint16_t));
        }
        if (esp_lcd_panel_draw_bitmap(panel_, x0, y, x0 + w, y + lines, dma_strip_) != ESP_OK)
            return false;
        // Do not reuse this DMA buffer until the transfer is acknowledged.
        if (xSemaphoreTake(dma_done_, pdMS_TO_TICKS(1000)) != pdTRUE) return false;
    }
    return true;
}

void RobotDisplay::LcdEntry(void* context) {
    auto* self = static_cast<RobotDisplay*>(context);
    while (true) {
        xSemaphoreTake(self->lcd_go_, portMAX_DELAY);
        self->lcd_ok_ = self->Flush(self->job_x0_, self->job_y0_, self->job_x1_, self->job_y1_);
        xSemaphoreGive(self->lcd_idle_);
    }
}

bool RobotDisplay::WaitLcdIdle() {
    xSemaphoreTake(lcd_idle_, portMAX_DELAY);
    const bool ok = lcd_ok_;
    xSemaphoreGive(lcd_idle_);
    return ok;
}

bool RobotDisplay::Submit() {
    xSemaphoreTake(lcd_idle_, portMAX_DELAY);
    if (!lcd_ok_) { xSemaphoreGive(lcd_idle_); return false; }
    int x0, y0, x1, y1;
    animation_->Dirty(&x0, &y0, &x1, &y1);
    const uint16_t* canvas = animation_->Canvas();
    std::memcpy(frame_copy_ + y0 * GifAnimation::kWidth, canvas + y0 * GifAnimation::kWidth,
                (y1 - y0) * GifAnimation::kWidth * sizeof(uint16_t));
    job_x0_ = x0; job_y0_ = y0; job_x1_ = x1; job_y1_ = y1;
    xSemaphoreGive(lcd_go_);
    return true;
}

void RobotDisplay::Post(EventKind kind, bool strong) {
    const Event event{kind, strong, NowMs()};
    if (events_ && xQueueSend(events_, &event, 0) != pdTRUE)
        ESP_LOGW(kTag, "Fila de eventos visuais cheia");
}
void RobotDisplay::Wake() { Post(EventKind::kWake); }
void RobotDisplay::Ready() { Post(EventKind::kReady); }
void RobotDisplay::Response() { Post(EventKind::kResponse); }
void RobotDisplay::Loading() { Post(EventKind::kLoading); }
void RobotDisplay::ObserveMotion(bool strong) { Post(EventKind::kMotion, strong); }
void RobotDisplay::Shake() { Post(EventKind::kShake); }
void RobotDisplay::Entry(void* context) {
    static_cast<RobotDisplay*>(context)->Run();
    vTaskDelete(nullptr);
}

void RobotDisplay::Run() {
    VisualStateMachine state(CONFIG_NUCLEA_DISPLAY_IDLE_MS);
    ShakeDetector motion;
    bool transition_finished = false;
    bool loop_open = false;
    int64_t due = 0;
    int64_t report_at = NowMs();
    int64_t decode_ms = 0, lcd_ms = 0, max_frame_ms = 0;
    unsigned frames = 0;
    Event event{};
    while (true) {
        const int64_t now = NowMs();
        const int64_t remaining = due - now;
        // With a 10 ms tick, a shorter wait rounds up to a full tick and drops frames: go early.
        const TickType_t wait = remaining >= portTICK_PERIOD_MS ? pdMS_TO_TICKS(remaining) : 0;
        if (xQueueReceive(events_, &event, wait) == pdTRUE) {
            switch (event.kind) {
                case EventKind::kWake: {
                    const bool was_sleeping = state.Clip() == VisualClip::kSleep;
                    state.Wake();
                    if (was_sleeping) {
                        // A wakeword interrupts only the idle loop, between completed LCD transfers.
                        animation_->Close();
                        loop_open = false;
                        transition_finished = false;
                        due = 0;
                    }
                    break;
                }
                case EventKind::kReady: state.Ready(event.timestamp); break;
                case EventKind::kResponse: state.Response(esp_random() % 100); break;
                case EventKind::kLoading: state.Loading(event.timestamp); break;
                case EventKind::kMotion:
                case EventKind::kShake:
                    if (event.kind == EventKind::kShake || motion.Observe(event.strong, event.timestamp)) {
                        if (state.Shake(event.timestamp)) {
                            ESP_LOGI(kTag, "Chacoalho confirmado; etapa=%u", state.ShakeCount());
                            if (state.TakeInterrupt()) {
                                animation_->Close();
                                loop_open = false;
                                transition_finished = false;
                                due = 0;
                            }
                        } else ESP_LOGW(kTag, "Fila de reacoes cheia; chacoalho ignorado");
                    }
                    break;
            }
        }
        if (state.LoadingDue(NowMs())) {
            // Cut the idle loop instead of waiting up to its full 8 s cycle.
            animation_->Close();
            loop_open = false;
            transition_finished = false;
            state.CycleComplete(NowMs());
            due = 0;
        }
        if (NowMs() + static_cast<int64_t>(portTICK_PERIOD_MS) <= due) continue;
        if (transition_finished) {
            state.CycleComplete(NowMs());
            transition_finished = false;
        }
        const VisualClip clip = state.Clip();
        const int64_t started = NowMs();
        int delay = 40;
        const char* path = ClipPath(clip);
        if (!loop_open) {
            loop_open = animation_->Open(path);
            if (!loop_open && clip != VisualClip::kSleep && clip != VisualClip::kBlink &&
                clip != VisualClip::kWake && clip != VisualClip::kClose) {
                ESP_LOGW(kTag, "GIF opcional invalido: %s; usando blink", path);
                loop_open = animation_->Open(kAwake);
            }
            ESP_LOGI(kTag, "Animacao: %s", path);
        }
        if (!loop_open) { ESP_LOGE(kTag, "Falha abrindo %s", path); return; }
        if (!animation_->Next(&delay)) {
            animation_->Close();
            loop_open = false;
            state.CycleComplete(started);
            due = started;
            continue;
        }
        const bool last_frame = animation_->LastFrame();
        const int64_t decoded = NowMs();
        // Decode of the next frame overlaps this transfer; the final hold waits for it to finish.
        if (!Submit() || (last_frame && !WaitLcdIdle())) {
            ESP_LOGE(kTag, "Transferencia LCD falhou; audio continua ativo"); return;
        }
        const int64_t rendered = NowMs();
        // Intermediate frames include rendering in the budget; never shorten the final hold.
        due = DisplayFrameDeadline(started, rendered, delay, last_frame);
        if (last_frame) {
            animation_->Close();
            loop_open = false;
            transition_finished = true;
        }
        ++frames;
        decode_ms += decoded - started;
        lcd_ms += rendered - decoded;
        max_frame_ms = std::max(max_frame_ms, rendered - started);
        if (rendered - report_at >= 5000) {
            ESP_LOGI(kTag, "perf core=0 frames=%u window_ms=%lld decode_avg_ms=%lld lcd_avg_ms=%lld frame_max_ms=%lld heap_internal=%u stack_free=%uB",
                     frames, static_cast<long long>(rendered - report_at),
                     static_cast<long long>(decode_ms / frames), static_cast<long long>(lcd_ms / frames),
                     static_cast<long long>(max_frame_ms),
                     static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                     static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));
            report_at = rendered;
            frames = 0;
            decode_ms = lcd_ms = max_frame_ms = 0;
        }
    }
}
