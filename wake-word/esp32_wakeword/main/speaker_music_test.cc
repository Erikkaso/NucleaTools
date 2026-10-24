#include "speaker_music_test.h"
#include "sdkconfig.h"

#ifdef CONFIG_NUCLEA_SPEAKER_ONLY_TEST
#include <cstdio>
#include "audio_speaker.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "freertos/task.h"

void RunSpeakerMusicTest() {
    constexpr const char* tag = "SPEAKER_TEST";
    ESP_LOGW(tag, "TESTE SOMENTE ALTO-FALANTE: musica local em loop, sem Wi-Fi/microfone/visor");
    esp_vfs_littlefs_conf_t filesystem = {};
    filesystem.base_path = "/speaker-test";
    filesystem.partition_label = "spiffs";
    filesystem.format_if_mount_failed = false;
    esp_err_t result = esp_vfs_littlefs_register(&filesystem);
    if (result != ESP_OK) {
        ESP_LOGE(tag, "Nao foi possivel montar a musica: %s", esp_err_to_name(result));
        return;
    }
    static AudioSpeaker speaker;
    result = speaker.Init(CONFIG_NUCLEA_SPEAKER_TEST_VOLUME_PERCENT);
    if (result != ESP_OK) {
        ESP_LOGE(tag, "Falha ao iniciar MAX98357A: %s", esp_err_to_name(result));
        return;
    }
    FILE* file = std::fopen("/speaker-test/music.pcm", "rb");
    if (!file) {
        ESP_LOGE(tag, "music.pcm ausente; execute prepare_speaker_music.py e grave o firmware completo");
        return;
    }
    // Read only 100 ms at a time; the existing bounded queue handles backpressure.
    uint8_t pcm[4800];
    unsigned loop = 0;
    while (true) {
        std::rewind(file);
        size_t total = 0;
        result = speaker.Begin();
        if (result != ESP_OK) break;
        ESP_LOGI(tag, "Reproduzindo musica: ciclo=%u volume=%d%%", ++loop,
                 CONFIG_NUCLEA_SPEAKER_TEST_VOLUME_PERCENT);
        while (true) {
            const size_t bytes = std::fread(pcm, 1, sizeof(pcm), file);
            if (!bytes) {
                if (std::ferror(file)) result = ESP_FAIL;
                break;
            }
            if (bytes % 2 || !speaker.Push(pcm, bytes)) { result = ESP_FAIL; break; }
            total += bytes;
        }
        if (!total && result == ESP_OK) result = ESP_ERR_INVALID_SIZE;
        if (result == ESP_OK) result = speaker.Finish();
        else speaker.Abort();
        if (result != ESP_OK) break;
        ESP_LOGI(tag, "Musica concluida: %u bytes, reiniciando", unsigned(total));
        vTaskDelay(pdMS_TO_TICKS(300));
    }
    speaker.Abort();
    std::fclose(file);
    ESP_LOGE(tag, "Teste interrompido: %s", esp_err_to_name(result));
}
#else
void RunSpeakerMusicTest() {}
#endif
