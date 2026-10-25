#pragma once
#include "esp_err.h"
#include "robot_display.h"
#include "sdkconfig.h"

#ifdef CONFIG_NUCLEA_PIEZO_ENABLED
#include "driver/pulse_cnt.h"

// Counts piezo pulses in hardware (PCNT with glitch filter) and feeds the
// display's shake detector every 20 ms. Logs pulse activity for calibration.
class PiezoSensor {
public:
    esp_err_t Start(RobotDisplay* display);
private:
    static void Entry(void* context);
    void Run();
    pcnt_unit_handle_t unit_ = nullptr;
    RobotDisplay* display_ = nullptr;
};
#else
class PiezoSensor {
public:
    esp_err_t Start(RobotDisplay*) { return ESP_OK; }
};
#endif
