#include "wifi_station.h"

#include <cstring>

#include "cJSON.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/task.h"
#include "http_parser.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "wifi_portal.h"
#include "auth_key.h"

namespace {
constexpr const char* kTag = "WIFI_STATION";
constexpr const char* kNamespace = "nuclea_wifi";
constexpr const char* kApSsid = "Nuclea-Config";
constexpr const char* kApPassword = "Nuclea-Dell2026";
constexpr char kDefaultGatewayUrl[] = "https://voice-gateway.200-129-37-25.sslip.io";
constexpr EventBits_t kGotIpBit = BIT0;
constexpr EventBits_t kDisconnectedBit = BIT1;
constexpr EventBits_t kReadyBit = BIT2;
constexpr uint32_t kConnectionTimeoutMs = 30000;
constexpr int64_t kPortalCloseDelayMs = 10000;

int64_t NowMs() { return esp_timer_get_time() / 1000; }

bool ValidSettings(const WifiSettings& settings) {
    if (settings.version != 1 || settings.ssid[0] == '\0' ||
        settings.ssid[32] != '\0' || settings.password[64] != '\0' ||
        settings.base_url[192] != '\0') return false;
    const size_t password_length = std::strlen(settings.password);
    if (password_length != 0 && password_length < 8) return false;
    if (password_length == 64 &&
        std::strspn(settings.password, "0123456789abcdefABCDEF") != 64) return false;

    const char* url = settings.base_url;
    if (std::strncmp(url, "http://", 7) != 0 &&
        std::strncmp(url, "https://", 8) != 0) return false;
    for (const unsigned char* p = reinterpret_cast<const unsigned char*>(url); *p; ++p) {
        if (*p <= 32 || *p == 127) return false;
    }
    http_parser_url parsed = {};
    if (http_parser_parse_url(url, std::strlen(url), 0, &parsed) != 0 ||
        !(parsed.field_set & (1 << UF_HOST)) ||
        (parsed.field_set & ((1 << UF_USERINFO) | (1 << UF_QUERY) | (1 << UF_FRAGMENT)))) return false;
    if (parsed.field_set & (1 << UF_PATH)) {
        const auto& path = parsed.field_data[UF_PATH];
        if (path.len != 1 || url[path.off] != '/') return false;
    }
    return true;
}

bool CopyJsonString(const cJSON* root, const char* key, char* target, size_t capacity) {
    const cJSON* field = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsString(field) || field->valuestring == nullptr ||
        std::strlen(field->valuestring) >= capacity) return false;
    std::memcpy(target, field->valuestring, std::strlen(field->valuestring) + 1);
    return true;
}

esp_err_t SendJson(httpd_req_t* request, cJSON* root) {
    if (root == nullptr) return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Sem memoria.");
    char* body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (body == nullptr) return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Sem memoria.");
    httpd_resp_set_type(request, "application/json");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    const esp_err_t result = httpd_resp_send(request, body, HTTPD_RESP_USE_STRLEN);
    cJSON_free(body);
    return result;
}

esp_err_t SendUnavailable(httpd_req_t* request, const char* message) {
    httpd_resp_set_status(request, "503 Service Unavailable");
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    return httpd_resp_send(request, message, HTTPD_RESP_USE_STRLEN);
}
}

void WifiStation::HandleEvent(void* context, esp_event_base_t base, int32_t id, void*) {
    auto* wifi = static_cast<WifiStation*>(context);
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi->events_, kGotIpBit | kReadyBit);
        xEventGroupSetBits(wifi->events_, kDisconnectedBit);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(wifi->events_, kGotIpBit);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        xEventGroupClearBits(wifi->events_, kGotIpBit | kReadyBit);
        xEventGroupSetBits(wifi->events_, kDisconnectedBit);
    }
}

esp_err_t WifiStation::Connect() {
    // Do not erase NVS on failure: it contains the user's saved configuration.
    ESP_RETURN_ON_ERROR(nvs_flash_init(), kTag, "nvs init");
    mutex_ = xSemaphoreCreateMutex();
    events_ = xEventGroupCreate();
    pending_ = xQueueCreate(1, sizeof(PendingSettings));
    if (mutex_ == nullptr || events_ == nullptr || pending_ == nullptr) return ESP_ERR_NO_MEM;

    nvs_handle_t nvs;
    ESP_RETURN_ON_ERROR(nvs_open(kNamespace, NVS_READWRITE, &nvs), kTag, "nvs open");
    size_t size = sizeof(settings_);
    const esp_err_t loaded = nvs_get_blob(nvs, "settings", &settings_, &size);
    if (loaded == ESP_OK && size == sizeof(settings_) && settings_.base_url[0] == '\0') {
        std::memcpy(settings_.base_url, kDefaultGatewayUrl, sizeof(kDefaultGatewayUrl));
    }
    if (loaded != ESP_OK || size != sizeof(settings_) || !ValidSettings(settings_))
        settings_ = WifiSettings{};
    size_t key_size = sizeof(auth_key_);
    if (nvs_get_str(nvs, "auth_key", auth_key_, &key_size) != ESP_OK ||
        !ValidAuthKey(auth_key_)) auth_key_[0] = '\0';
    nvs_close(nvs);

    gpio_config_t button = {};
    button.pin_bit_mask = 1ULL << GPIO_NUM_0;
    button.mode = GPIO_MODE_INPUT;
    button.pull_up_en = GPIO_PULLUP_ENABLE;
    button.pull_down_en = GPIO_PULLDOWN_DISABLE;
    button.intr_type = GPIO_INTR_DISABLE;
    ESP_RETURN_ON_ERROR(gpio_config(&button), kTag, "BOOT button GPIO");
    ESP_LOGI(kTag, "Segure BOOT por 3 segundos para reabrir o portal Wi-Fi.");

    ESP_RETURN_ON_ERROR(esp_netif_init(), kTag, "netif init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), kTag, "event loop");
    if (esp_netif_create_default_wifi_sta() == nullptr ||
        esp_netif_create_default_wifi_ap() == nullptr) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), kTag, "wifi init");
    // Persist only the validated application blob, never a trial password.
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), kTag, "wifi storage");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
                                                &HandleEvent, this), kTag, "wifi events");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID,
                                                &HandleEvent, this), kTag, "ip events");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), kTag, "wifi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_ps(WIFI_PS_NONE), kTag, "wifi power save");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), kTag, "wifi start");
    if (xTaskCreate(&WorkerEntry, "wifi_config", 6144, this, 4, nullptr) != pdPASS) return ESP_ERR_NO_MEM;

    // The worker opens the portal while app_main waits for a usable configuration.
    xEventGroupWaitBits(events_, kReadyBit, pdFALSE, pdTRUE, portMAX_DELAY);
    return ESP_OK;
}

bool WifiStation::IsConnected() const {
    return events_ != nullptr && (xEventGroupGetBits(events_) & kReadyBit) != 0;
}

std::string WifiStation::InterfaceUrl() const {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    const std::string url(settings_.base_url);
    xSemaphoreGive(mutex_);
    return url;
}

std::string WifiStation::AuthKey() const {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    const std::string key(auth_key_);
    xSemaphoreGive(mutex_);
    return key;
}

void WifiStation::SetStatus(const char* message, bool busy) {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    message_ = message;
    busy_ = busy;
    xSemaphoreGive(mutex_);
}

esp_err_t WifiStation::SaveSettings(const WifiSettings& settings, const char* auth_key) {
    nvs_handle_t nvs;
    esp_err_t result = nvs_open(kNamespace, NVS_READWRITE, &nvs);
    if (result != ESP_OK) return result;
    result = nvs_set_blob(nvs, "settings", &settings, sizeof(settings));
    if (result == ESP_OK) result = nvs_set_str(nvs, "auth_key", auth_key);
    if (result == ESP_OK) result = nvs_commit(nvs);
    nvs_close(nvs);
    return result;
}

bool WifiStation::TryConnect(const WifiSettings& settings, uint32_t timeout_ms) {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    connecting_ = true;
    xSemaphoreGive(mutex_);
    esp_wifi_disconnect();
    vTaskDelay(pdMS_TO_TICKS(100));
    xEventGroupClearBits(events_, kGotIpBit | kReadyBit | kDisconnectedBit);
    wifi_config_t config = {};
    std::memcpy(config.sta.ssid, settings.ssid, std::strlen(settings.ssid));
    std::memcpy(config.sta.password, settings.password, std::strlen(settings.password));
    config.sta.threshold.authmode = settings.password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    esp_err_t result = esp_wifi_set_config(WIFI_IF_STA, &config);
    if (result == ESP_OK) result = esp_wifi_connect();
    const int64_t deadline = NowMs() + timeout_ms;
    bool connected = false;
    while (result == ESP_OK && NowMs() < deadline) {
        PollPortalButton();
        const EventBits_t bits = xEventGroupWaitBits(events_, kGotIpBit | kDisconnectedBit,
                                                   pdFALSE, pdFALSE, pdMS_TO_TICKS(250));
        if (bits & kGotIpBit) { connected = true; break; }
        if (bits & kDisconnectedBit) {
            xEventGroupClearBits(events_, kDisconnectedBit);
            vTaskDelay(pdMS_TO_TICKS(250));
            result = esp_wifi_connect();
        }
    }
    if (!connected) esp_wifi_disconnect();
    xSemaphoreTake(mutex_, portMAX_DELAY);
    connecting_ = false;
    xSemaphoreGive(mutex_);
    return connected;
}

void WifiStation::WorkerEntry(void* context) {
    static_cast<WifiStation*>(context)->Run();
}

void WifiStation::PollPortalButton() {
    if (!portal_button_.Update(gpio_get_level(GPIO_NUM_0) == 0, NowMs())) return;
    const esp_err_t result = StartPortal();
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "BOOT: falha ao abrir portal: %s", esp_err_to_name(result));
        return;
    }
    manual_portal_ = true;
    xSemaphoreTake(mutex_, portMAX_DELAY);
    if (!busy_ && !connecting_)
        message_ = "Portal aberto pelo BOOT. Altere a configuracao e clique em Conectar e salvar.";
    xSemaphoreGive(mutex_);
    ESP_LOGI(kTag, "Portal reaberto por BOOT; configuracao salva preservada.");
}

void WifiStation::Run() {
    if (ValidSettings(settings_) && TryConnect(settings_, kConnectionTimeoutMs)) {
        xEventGroupSetBits(events_, kReadyBit);
        SetStatus("Conectado.", false);
    } else {
        const esp_err_t result = StartPortal();
        if (result != ESP_OK) ESP_LOGE(kTag, "Portal: %s", esp_err_to_name(result));
    }
    int64_t disconnected_at = NowMs();
    int64_t close_portal_at = 0;
    int64_t retry_at = NowMs() + 10000;
    PendingSettings pending;
    WifiSettings& candidate = pending.settings;
    while (true) {
        PollPortalButton();
        if (manual_portal_) close_portal_at = 0;
        if (xQueueReceive(pending_, &pending, pdMS_TO_TICKS(250)) == pdTRUE) {
            close_portal_at = 0;
            const bool connected = TryConnect(candidate, kConnectionTimeoutMs);
            const esp_err_t saved = connected ? SaveSettings(candidate, pending.auth_key) : ESP_FAIL;
            if (saved == ESP_OK) {
                manual_portal_ = false;
                xSemaphoreTake(mutex_, portMAX_DELAY);
                settings_ = candidate;
                std::memcpy(auth_key_, pending.auth_key, sizeof(auth_key_));
                xSemaphoreGive(mutex_);
                xEventGroupSetBits(events_, kReadyBit);
                SetStatus("Conectado. Configuracao salva; o portal fechara em 10 segundos.", false);
                close_portal_at = NowMs() + kPortalCloseDelayMs;
                ESP_LOGI(kTag, "Wi-Fi e endereco da interface salvos.");
            } else {
                esp_wifi_disconnect();
                xEventGroupClearBits(events_, kGotIpBit | kReadyBit);
                SetStatus(connected ? "Falha ao salvar na flash. Configuracao anterior mantida."
                                    : "Nao conectou. Confira rede e senha; configuracao anterior mantida.", false);
            }
            pending = PendingSettings{};
            retry_at = NowMs() + 10000;
            disconnected_at = NowMs();
        }
        const int64_t now = NowMs();
        if (IsConnected()) {
            disconnected_at = now;
            if (!manual_portal_ && server_ != nullptr && close_portal_at != 0 && now >= close_portal_at) {
                StopPortal();
                close_portal_at = 0;
            }
            continue;
        }
        close_portal_at = 0;
        if (server_ == nullptr && now - disconnected_at >= kConnectionTimeoutMs) {
            const esp_err_t result = StartPortal();
            if (result != ESP_OK) ESP_LOGE(kTag, "Portal: %s", esp_err_to_name(result));
        }
        if (ValidSettings(settings_) && now >= retry_at) {
            if (TryConnect(settings_, 5000)) {
                xEventGroupSetBits(events_, kReadyBit);
                if (server_ != nullptr && !manual_portal_) close_portal_at = NowMs() + kPortalCloseDelayMs;
                xSemaphoreTake(mutex_, portMAX_DELAY);
                if (!busy_) message_ = "Reconectado a rede salva.";
                xSemaphoreGive(mutex_);
            }
            retry_at = NowMs() + 10000;
        }
    }
}

esp_err_t WifiStation::StartPortal() {
    if (server_ != nullptr) return ESP_OK;
    wifi_config_t ap = {};
    std::memcpy(ap.ap.ssid, kApSsid, std::strlen(kApSsid));
    ap.ap.ssid_len = std::strlen(kApSsid);
    std::memcpy(ap.ap.password, kApPassword, std::strlen(kApPassword));
    ap.ap.channel = 1;
    ap.ap.max_connection = 2;
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), kTag, "portal mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap), kTag, "portal AP");
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 6144;
    config.lru_purge_enable = true;
    ESP_RETURN_ON_ERROR(httpd_start(&server_, &config), kTag, "portal HTTP");
    const httpd_uri_t routes[] = {
        {"/", HTTP_GET, &HandlePage, this},
        {"/api/status", HTTP_GET, &HandleStatus, this},
        {"/api/networks", HTTP_GET, &HandleScan, this},
        {"/api/config", HTTP_POST, &HandleConfigure, this},
    };
    for (const auto& route : routes) {
        const esp_err_t result = httpd_register_uri_handler(server_, &route);
        if (result != ESP_OK) { StopPortal(); return result; }
    }
    ESP_LOGW(kTag, "Portal: rede=%s senha=%s endereco=http://192.168.4.1", kApSsid, kApPassword);
    return ESP_OK;
}

void WifiStation::StopPortal() {
    if (server_ != nullptr) { httpd_stop(server_); server_ = nullptr; }
    esp_wifi_set_mode(WIFI_MODE_STA);
}

bool WifiStation::AllowRequest(httpd_req_t* request) {
    // The HTTP server listens on both interfaces; restrict configuration to SoftAP.
    sockaddr_storage local = {};
    socklen_t length = sizeof(local);
    bool local_ok = false;
    if (getsockname(httpd_req_to_sockfd(request), reinterpret_cast<sockaddr*>(&local), &length) == 0) {
        if (local.ss_family == AF_INET && length >= sizeof(sockaddr_in)) {
            const auto* ipv4 = reinterpret_cast<const sockaddr_in*>(&local);
            local_ok = ipv4->sin_addr.s_addr == inet_addr("192.168.4.1");
        }
#if CONFIG_LWIP_IPV6
        else if (local.ss_family == AF_INET6 && length >= sizeof(sockaddr_in6)) {
            // ESP-IDF's dual-stack server returns IPv4-mapped IPv6 addresses.
            const auto* ipv6 = reinterpret_cast<const sockaddr_in6*>(&local);
            in6_addr expected = {};
            local_ok = inet_pton(AF_INET6, "::ffff:192.168.4.1", &expected) == 1 &&
                std::memcmp(&ipv6->sin6_addr, &expected, sizeof(expected)) == 0;
        }
#endif
    }
    char origin[64] = {};
    const size_t origin_length = httpd_req_get_hdr_value_len(request, "Origin");
    const bool origin_ok = origin_length == 0 ||
        (origin_length < sizeof(origin) &&
         httpd_req_get_hdr_value_str(request, "Origin", origin, sizeof(origin)) == ESP_OK &&
         (std::strcmp(origin, "http://192.168.4.1") == 0 ||
          std::strcmp(origin, "http://192.168.4.1:80") == 0));
    char host[32] = {};
    const bool host_ok = httpd_req_get_hdr_value_str(request, "Host", host, sizeof(host)) == ESP_OK &&
        (std::strcmp(host, "192.168.4.1") == 0 || std::strcmp(host, "192.168.4.1:80") == 0);
    if (!origin_ok || !host_ok || !local_ok) {
        ESP_LOGW(kTag, "Portal negado: Host=%d Origin=%d destino_AP=%d familia=%d",
                 host_ok, origin_ok, local_ok, local.ss_family);
        httpd_resp_send_err(request, HTTPD_403_FORBIDDEN, "Acesse pela rede Nuclea-Config.");
        return false;
    }
    return true;
}

esp_err_t WifiStation::HandlePage(httpd_req_t* request) {
    if (!AllowRequest(request)) return ESP_OK;
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "X-Content-Type-Options", "nosniff");
    return httpd_resp_send(request, kWifiPortalHtml, HTTPD_RESP_USE_STRLEN);
}

esp_err_t WifiStation::HandleStatus(httpd_req_t* request) {
    if (!AllowRequest(request)) return ESP_OK;
    auto* wifi = static_cast<WifiStation*>(request->user_ctx);
    cJSON* root = cJSON_CreateObject();
    if (root != nullptr) {
        xSemaphoreTake(wifi->mutex_, portMAX_DELAY);
        cJSON_AddBoolToObject(root, "busy", wifi->busy_);
        cJSON_AddBoolToObject(root, "connected", wifi->IsConnected());
        cJSON_AddStringToObject(root, "message", wifi->message_);
        cJSON_AddStringToObject(root, "ssid", wifi->settings_.ssid);
        cJSON_AddStringToObject(root, "base_url", wifi->settings_.base_url);
        cJSON_AddBoolToObject(root, "auth_configured", wifi->auth_key_[0] != '\0');
        xSemaphoreGive(wifi->mutex_);
    }
    return SendJson(request, root);
}

esp_err_t WifiStation::HandleScan(httpd_req_t* request) {
    if (!AllowRequest(request)) return ESP_OK;
    auto* wifi = static_cast<WifiStation*>(request->user_ctx);
    xSemaphoreTake(wifi->mutex_, portMAX_DELAY);
    const bool connecting = wifi->connecting_ || wifi->busy_;
    if (connecting) {
        xSemaphoreGive(wifi->mutex_);
        return SendUnavailable(request, "Conexao em andamento. Tente novamente.");
    }
    // Serialize scan and connect; the Wi-Fi driver cannot run both at once.
    wifi_scan_config_t scan = {};
    esp_err_t result = esp_wifi_scan_start(&scan, true);
    wifi_ap_record_t records[16] = {};
    uint16_t count = 16;
    if (result == ESP_OK) result = esp_wifi_scan_get_ap_records(&count, records);
    xSemaphoreGive(wifi->mutex_);
    if (result != ESP_OK) return SendUnavailable(request, "Nao foi possivel buscar redes.");
    cJSON* root = cJSON_CreateArray();
    if (root != nullptr) {
        for (uint16_t i = 0; i < count; ++i) {
            if (records[i].ssid[0]) cJSON_AddItemToArray(root,
                cJSON_CreateString(reinterpret_cast<const char*>(records[i].ssid)));
        }
    }
    return SendJson(request, root);
}

esp_err_t WifiStation::HandleConfigure(httpd_req_t* request) {
    if (!AllowRequest(request)) return ESP_OK;
    if (request->content_len == 0 || request->content_len >= 1024)
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Configuracao muito grande ou vazia.");
    char body[1024] = {};
    size_t received = 0;
    while (received < request->content_len) {
        const int count = httpd_req_recv(request, body + received, request->content_len - received);
        if (count <= 0) return httpd_resp_send_err(request, HTTPD_408_REQ_TIMEOUT, "Envie novamente.");
        received += count;
    }
    cJSON* root = cJSON_ParseWithOpts(body, nullptr, true);
    auto* wifi = static_cast<WifiStation*>(request->user_ctx);
    PendingSettings pending;
    WifiSettings& candidate = pending.settings;
    xSemaphoreTake(wifi->mutex_, portMAX_DELAY);
    std::memcpy(pending.auth_key, wifi->auth_key_, sizeof(pending.auth_key));
    std::memcpy(candidate.base_url, wifi->settings_.base_url, sizeof(candidate.base_url));
    xSemaphoreGive(wifi->mutex_);
    if (!candidate.base_url[0])
        std::memcpy(candidate.base_url, kDefaultGatewayUrl, sizeof(kDefaultGatewayUrl));
    const cJSON* url = cJSON_GetObjectItemCaseSensitive(root, "base_url");
    bool valid_url = !url || (cJSON_IsString(url) && url->valuestring);
    if (valid_url && url && url->valuestring[0])
        valid_url = CopyJsonString(root, "base_url", candidate.base_url, sizeof(candidate.base_url));
    const cJSON* key = cJSON_GetObjectItemCaseSensitive(root, "auth_key");
    bool valid_key = !key || (cJSON_IsString(key) && key->valuestring);
    if (valid_key && key && key->valuestring[0]) {
        valid_key = ValidAuthKey(key->valuestring);
        if (valid_key) std::memcpy(pending.auth_key, key->valuestring, std::strlen(key->valuestring) + 1);
    }
    const bool valid = cJSON_IsObject(root) &&
        CopyJsonString(root, "ssid", candidate.ssid, sizeof(candidate.ssid)) &&
        CopyJsonString(root, "password", candidate.password, sizeof(candidate.password)) &&
        ValidSettings(candidate) && valid_url && valid_key &&
        (!pending.auth_key[0] || std::strncmp(candidate.base_url, "https://", 8) == 0);
    cJSON_Delete(root);
    if (!valid) return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
        "Informe rede, senha, URL base HTTPS com chave e chave de 32 a 128 caracteres ASCII sem espacos.");
    xSemaphoreTake(wifi->mutex_, portMAX_DELAY);
    if (wifi->busy_ || wifi->connecting_ || xQueueSend(wifi->pending_, &pending, 0) != pdTRUE) {
        xSemaphoreGive(wifi->mutex_);
        httpd_resp_set_status(request, "409 Conflict");
        return httpd_resp_send(request, "Aguarde a tentativa atual.", HTTPD_RESP_USE_STRLEN);
    }
    wifi->busy_ = true;
    wifi->message_ = "Testando conexao. Aguarde ate 30 segundos.";
    xSemaphoreGive(wifi->mutex_);
    httpd_resp_set_status(request, "202 Accepted");
    httpd_resp_set_type(request, "application/json");
    return httpd_resp_send(request, "{\"status\":\"testing\"}", HTTPD_RESP_USE_STRLEN);
}
