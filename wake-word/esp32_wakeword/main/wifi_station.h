#pragma once

#include <cstdint>
#include <string>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

struct WifiSettings {
    uint32_t version = 1;
    char ssid[33] = {};
    char password[65] = {};
    char base_url[193] = {};
};

class WifiStation {
public:
    esp_err_t Connect();
    bool IsConnected() const;
    std::string InterfaceUrl() const;

private:
    static void HandleEvent(void* context, esp_event_base_t base, int32_t id, void* data);
    static void WorkerEntry(void* context);
    static esp_err_t HandlePage(httpd_req_t* request);
    static esp_err_t HandleStatus(httpd_req_t* request);
    static esp_err_t HandleScan(httpd_req_t* request);
    static esp_err_t HandleConfigure(httpd_req_t* request);
    static bool AllowRequest(httpd_req_t* request);
    void Run();
    bool TryConnect(const WifiSettings& settings, uint32_t timeout_ms);
    esp_err_t StartPortal();
    void StopPortal();
    void SetStatus(const char* message, bool busy);
    esp_err_t SaveSettings(const WifiSettings& settings);

    EventGroupHandle_t events_ = nullptr;
    QueueHandle_t pending_ = nullptr;
    SemaphoreHandle_t mutex_ = nullptr;
    httpd_handle_t server_ = nullptr;
    WifiSettings settings_;
    const char* message_ = "Configure sua rede Wi-Fi.";
    bool busy_ = false;
    bool connecting_ = false;
};
