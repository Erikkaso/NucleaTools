#include "robot_display.h"
#include <algorithm>
#include <cstring>
#include <new>
#include "device_pins.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "sdkconfig.h"

namespace {
constexpr const char* kTag = "ROBOT_DISPLAY";
constexpr int kStripLines = 16;
constexpr size_t kCacheLimit = 5 * 1024 * 1024;
constexpr const char* kSleep = "/robot/sleep.gif";
constexpr const char* kWake = "/robot/wake.gif";
constexpr const char* kAwake = "/robot/nuclea-blink.gif";
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
    for (const char* asset : {kSleep, kWake, kAwake}) {
        if (!animation_->Open(asset)) {
            ESP_LOGE(kTag, "GIF ausente ou invalido (esperado 280x240): %s", asset);
            return ESP_ERR_NOT_FOUND;
        }
        animation_->Close();
    }
    if (!PrepareTransition()) ESP_LOGW(kTag, "Sem cache reverso: troca direta entre poses");
    ESP_RETURN_ON_ERROR(InitPanel(), kTag, "ST7789 init");
    events_ = xQueueCreate(8, sizeof(Event));
    if (!events_) return ESP_ERR_NO_MEM;
    if (xTaskCreatePinnedToCore(Entry, "robot_display", 6144, this, 1, nullptr, 1) != pdPASS) {
        vQueueDelete(events_);
        events_ = nullptr;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
#endif
}

bool RobotDisplay::PrepareTransition() {
    if (!animation_->Open(kWake)) return false;
    GIFINFO info = {};
    const bool valid = animation_->Info(&info) && info.iFrameCount > 1 && info.iFrameCount <= 128 &&
        static_cast<size_t>(info.iFrameCount) <= kCacheLimit / GifAnimation::kFrameBytes;
    if (!valid) { animation_->Close(); return false; }
    const size_t bytes = info.iFrameCount * GifAnimation::kFrameBytes;
    transition_ = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!transition_) { animation_->Close(); return false; }
    // Reopen after metadata scan. Cache fully composited frames, without skipping.
    bool good = animation_->Open(kWake);
    int count = 0;
    for (; good && count < info.iFrameCount; ++count) {
        int delay = 0;
        good = animation_->Next(&delay);
        if (good) {
            std::memcpy(transition_ + count * GifAnimation::kPixels,
                        animation_->Canvas(), GifAnimation::kFrameBytes);
            delays_[count] = static_cast<uint16_t>(std::clamp(delay, 10, 65535));
        }
    }
    animation_->Close();
    if (!good || count != info.iFrameCount) {
        heap_caps_free(transition_);
        transition_ = nullptr;
        return false;
    }
    frame_count_ = count;
    ESP_LOGI(kTag, "Cache wake: %d frames, %u bytes PSRAM", frame_count_, static_cast<unsigned>(bytes));
    return true;
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
    if (!dma_done_ || !dma_strip_) return ESP_ERR_NO_MEM;
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

bool RobotDisplay::Flush(const uint16_t* pixels) {
    for (int y = 0; y < GifAnimation::kHeight; y += kStripLines) {
        const int lines = std::min(kStripLines, GifAnimation::kHeight - y);
        std::memcpy(dma_strip_, pixels + y * GifAnimation::kWidth,
                    lines * GifAnimation::kWidth * sizeof(uint16_t));
        if (esp_lcd_panel_draw_bitmap(panel_, 0, y, GifAnimation::kWidth, y + lines, dma_strip_) != ESP_OK)
            return false;
        // Do not reuse this DMA buffer until the transfer is acknowledged.
        if (xSemaphoreTake(dma_done_, pdMS_TO_TICKS(1000)) != pdTRUE) return false;
    }
    return true;
}

void RobotDisplay::Post(Event event) {
    if (events_ && xQueueSend(events_, &event, 0) != pdTRUE)
        ESP_LOGW(kTag, "Fila de eventos visuais cheia");
}
void RobotDisplay::Wake() { Post(Event::kWake); }
void RobotDisplay::Ready() { Post(Event::kReady); }
void RobotDisplay::Entry(void* context) {
    static_cast<RobotDisplay*>(context)->Run();
    vTaskDelete(nullptr);
}

void RobotDisplay::Run() {
    VisualStateMachine state(CONFIG_NUCLEA_DISPLAY_IDLE_MS);
    VisualState previous = VisualState::kSleeping;
    int position = 0;
    bool transition_finished = false;
    bool loop_open = false;
    int64_t due = 0;
    Event event;
    while (true) {
        const int64_t now = NowMs();
        if (xQueueReceive(events_, &event, pdMS_TO_TICKS(std::max<int64_t>(0, due - now))) == pdTRUE) {
            if (event == Event::kWake) {
                if (state.State() == VisualState::kClosing) position = std::max(0, position - 1);
                state.Wake();
            }
            else state.Ready(NowMs());
        }
        if (state.State() == previous && transition_finished && NowMs() >= due) {
            state.TransitionComplete(NowMs());
            transition_finished = false;
        }
        state.Tick(NowMs());
        const VisualState current = state.State();
        if (current != previous) {
            transition_finished = false;
            animation_->Close();
            loop_open = false;
            if (current == VisualState::kWaking && previous != VisualState::kClosing) position = frame_count_ - 1;
            if (current == VisualState::kClosing) position = 0;
            due = 0;
            ESP_LOGI(kTag, "Estado visual: %d", static_cast<int>(current));
            previous = current;
        }
        if (NowMs() < due) continue;
        const int64_t started = NowMs();
        int delay = 40;
        const uint16_t* pixels = nullptr;
        if (current == VisualState::kWaking || current == VisualState::kClosing) {
            if (!transition_) {
                state.TransitionComplete(started);
                due = started;
                continue;
            }
            position = std::clamp(position, 0, frame_count_ - 1);
            pixels = transition_ + position * GifAnimation::kPixels;
            delay = delays_[position];
            if (current == VisualState::kWaking) transition_finished = position-- == 0;
            else transition_finished = position++ == frame_count_ - 1;
        } else {
            const char* path = current == VisualState::kSleeping ? kSleep : kAwake;
            if (!loop_open) loop_open = animation_->Open(path);
            if (!loop_open) { ESP_LOGE(kTag, "Falha abrindo %s", path); return; }
            if (!animation_->Next(&delay)) {
                animation_->Close();
                loop_open = false;
                due = started + 10;
                continue;
            }
            pixels = animation_->Canvas();
        }
        if (!Flush(pixels)) { ESP_LOGE(kTag, "Transferencia LCD falhou; audio continua ativo"); return; }
        due = std::max(started + std::max(delay, 10), NowMs() + 10);
    }
}
