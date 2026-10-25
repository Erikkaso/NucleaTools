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
    // Recording was handed to the model; shows the loading animation until Response/Ready.
    void Loading();
    // Continuous sensor adapter: call every 20 ms with a conditioned motion envelope.
    void ObserveMotion(bool strong);
    // Already confirmed shake (e.g. a knock pattern); skips the envelope detector.
    void Shake();
private:
    enum class EventKind { kWake, kReady, kResponse, kMotion, kShake, kLoading };
    struct Event { EventKind kind; bool strong; int64_t timestamp; };
    static void Entry(void* context);
    static bool TransferDone(esp_lcd_panel_io_handle_t io,
                             esp_lcd_panel_io_event_data_t* event, void* context);
    esp_err_t InitPanel();
    // Copies the dirty band and hands it to the LCD task; returns once the PREVIOUS
    // transfer finished, so decoding of the next frame overlaps this transfer.
    bool Submit();
    bool WaitLcdIdle();
    bool Flush(int x0, int y0, int x1, int y1);
    static void LcdEntry(void* context);
    void Run();
    void Post(EventKind kind, bool strong = false);
    QueueHandle_t events_ = nullptr;
    SemaphoreHandle_t dma_done_ = nullptr;
    esp_lcd_panel_io_handle_t io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    uint16_t* dma_strip_ = nullptr;
    uint16_t* frame_copy_ = nullptr;
    SemaphoreHandle_t lcd_go_ = nullptr;
    SemaphoreHandle_t lcd_idle_ = nullptr;
    int job_x0_ = 0, job_y0_ = 0, job_x1_ = 0, job_y1_ = 0;
    bool lcd_ok_ = true;
    GifAnimation* animation_ = nullptr;
};
