#include "piezo_sensor.h"
#ifdef CONFIG_NUCLEA_PIEZO_ENABLED
#include "device_pins.h"
#include "driver/gpio.h"
#include <algorithm>
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "knock_detector.h"
#include "sustained_motion.h"

namespace {
constexpr const char* kTag = "PIEZO";
constexpr int kSampleMs = 20;  // ShakeDetector treats gaps above 100 ms as lost samples.
#ifdef CONFIG_NUCLEA_PIEZO_PULLDOWN
constexpr bool kPulldown = true;
#else
constexpr bool kPulldown = false;
#endif
}

esp_err_t PiezoSensor::Start(RobotDisplay* display) {
    if (unit_) return ESP_OK;
    display_ = display;
    pcnt_unit_config_t unit_config = {};
    unit_config.low_limit = -1;
    unit_config.high_limit = 32767;
    ESP_RETURN_ON_ERROR(pcnt_new_unit(&unit_config, &unit_), kTag, "PCNT unit");
    // Ignore sub-microsecond glitches; real piezo pulses last much longer.
    pcnt_glitch_filter_config_t filter = {};
    filter.max_glitch_ns = 1000;
    ESP_RETURN_ON_ERROR(pcnt_unit_set_glitch_filter(unit_, &filter), kTag, "PCNT filter");
    pcnt_chan_config_t channel_config = {};
    channel_config.edge_gpio_num = DevicePins::kPiezo;
    channel_config.level_gpio_num = -1;
    pcnt_channel_handle_t channel = nullptr;
    ESP_RETURN_ON_ERROR(pcnt_new_channel(unit_, &channel_config, &channel), kTag, "PCNT channel");
    ESP_RETURN_ON_ERROR(pcnt_channel_set_edge_action(channel, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                                     PCNT_CHANNEL_EDGE_ACTION_HOLD), kTag, "PCNT edge");
    // PCNT enables the pull-up; a piezo needs a path to GND instead.
    gpio_pullup_dis(static_cast<gpio_num_t>(DevicePins::kPiezo));
    if (kPulldown) gpio_pulldown_en(static_cast<gpio_num_t>(DevicePins::kPiezo));
    else gpio_pulldown_dis(static_cast<gpio_num_t>(DevicePins::kPiezo));
    ESP_RETURN_ON_ERROR(pcnt_unit_enable(unit_), kTag, "PCNT enable");
    ESP_RETURN_ON_ERROR(pcnt_unit_clear_count(unit_), kTag, "PCNT clear");
    ESP_RETURN_ON_ERROR(pcnt_unit_start(unit_), kTag, "PCNT start");
    if (xTaskCreatePinnedToCore(Entry, "piezo", 3072, this, 2, nullptr, 0) != pdPASS)
        return ESP_ERR_NO_MEM;
#ifdef CONFIG_NUCLEA_PIEZO_KNOCK_MODE
    ESP_LOGI(kTag, "GPIO %d, pull-down interno=%d, modo batidas: %d em %d ms",
             DevicePins::kPiezo, int(kPulldown),
             CONFIG_NUCLEA_PIEZO_KNOCKS, CONFIG_NUCLEA_PIEZO_KNOCK_WINDOW_MS);
#else
    ESP_LOGI(kTag, "GPIO %d, pull-down interno=%d, modo chacoalho: minimo %d ms continuos, %d pulsos/100ms",
             DevicePins::kPiezo, int(kPulldown),
             CONFIG_NUCLEA_PIEZO_SHAKE_BUCKETS * 100, CONFIG_NUCLEA_PIEZO_MIN_PULSES);
#endif
    return ESP_OK;
}

void PiezoSensor::Entry(void* context) { static_cast<PiezoSensor*>(context)->Run(); }

void PiezoSensor::Run() {
#ifdef CONFIG_NUCLEA_PIEZO_KNOCK_MODE
    KnockDetector knocks(CONFIG_NUCLEA_PIEZO_KNOCKS, CONFIG_NUCLEA_PIEZO_KNOCK_WINDOW_MS);
#else
    SustainedMotion motion(CONFIG_NUCLEA_PIEZO_SHAKE_BUCKETS, CONFIG_NUCLEA_PIEZO_MIN_PULSES);
#endif
    unsigned second_pulses = 0, second_strong = 0, second_peak = 0;
    unsigned total_pulses = 0, quiet_seconds = 0;
    int64_t report_at = esp_timer_get_time() / 1000 + 1000;
    TickType_t wake = xTaskGetTickCount();
    while (true) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(kSampleMs));
        int count = 0;
        if (pcnt_unit_get_count(unit_, &count) == ESP_OK && count > 0) pcnt_unit_clear_count(unit_);
        else count = 0;
        const int64_t now = esp_timer_get_time() / 1000;
#ifdef CONFIG_NUCLEA_PIEZO_KNOCK_MODE
        const unsigned before = knocks.Knocks();
        const bool strong = knocks.Observe(count > 0, now);
        if (strong) {
            ESP_LOGI(kTag, "Batidas confirmadas (%d em ate %d ms)",
                     CONFIG_NUCLEA_PIEZO_KNOCKS, CONFIG_NUCLEA_PIEZO_KNOCK_WINDOW_MS);
            display_->Shake();
        } else if (knocks.Knocks() > before) {
            ESP_LOGI(kTag, "Batida %u/%d", knocks.Knocks(), CONFIG_NUCLEA_PIEZO_KNOCKS);
        }
#else
        const bool strong = motion.Observe(static_cast<unsigned>(count), now);
        if (strong) {
            ESP_LOGI(kTag, "Chacoalho confirmado");
            display_->Shake();
        }
#endif
        second_pulses += count;
        second_peak = std::max(second_peak, static_cast<unsigned>(count));
        total_pulses += count;
        second_strong += strong;
        if (now >= report_at) {
            // Only report activity, so a quiet sensor does not flood the monitor.
            if (second_pulses) {
                ESP_LOGI(kTag, "pulsos=%u pico=%u/%dms forte=%u/%u amostras", second_pulses, second_peak,
                         kSampleMs, second_strong, unsigned(1000 / kSampleMs));
                quiet_seconds = 0;
            } else if (++quiet_seconds % 5 == 0) {
                ESP_LOGI(kTag, "ativo; sem pulsos ha %us (total=%u, nivel do pino=%d)",
                         quiet_seconds, total_pulses, gpio_get_level(static_cast<gpio_num_t>(DevicePins::kPiezo)));
            }
            second_pulses = second_strong = second_peak = 0;
            report_at = now + 1000;
        }
    }
}
#endif
