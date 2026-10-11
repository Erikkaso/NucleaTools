#pragma once
#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "gif_animation.h"
#include "visual_state.h"

class RobotDisplay {
public:
    esp_err_t Start();
    void Wake();
    void Ready();
private:
    enum class Event { kWake, kReady };
    static void Entry(void* context);
    static bool TransferDone(esp_lcd_panel_io_handle_t io,
                             esp_lcd_panel_io_event_data_t* event, void* context);
    esp_err_t InitPanel();
    bool PrepareTransition();
    bool Flush(const uint16_t* pixels);
    void Run();
    void Post(Event event);
    QueueHandle_t events_ = nullptr;
    SemaphoreHandle_t dma_done_ = nullptr;
    esp_lcd_panel_io_handle_t io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    uint16_t* dma_strip_ = nullptr;
    GifAnimation* animation_ = nullptr;
    uint16_t* transition_ = nullptr;
    uint16_t delays_[128] = {};
    int frame_count_ = 0;
};
