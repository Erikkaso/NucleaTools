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
    void Response();
    // Future sensor adapter: call every 20 ms with a conditioned motion envelope.
    void ObserveMotion(bool strong);
private:
    enum class EventKind { kWake, kReady, kResponse, kMotion };
    struct Event { EventKind kind; bool strong; int64_t timestamp; };
    static void Entry(void* context);
    static bool TransferDone(esp_lcd_panel_io_handle_t io,
                             esp_lcd_panel_io_event_data_t* event, void* context);
    esp_err_t InitPanel();
    bool PrepareTransition();
    bool Flush(const uint16_t* pixels, bool mirror_x);
    void Run();
    void Post(EventKind kind, bool strong = false);
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
