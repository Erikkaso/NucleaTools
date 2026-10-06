#include "driver/i2s_std.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

constexpr gpio_num_t PIN_SCK = GPIO_NUM_11;
constexpr gpio_num_t PIN_WS = GPIO_NUM_10;
constexpr gpio_num_t PIN_SD = GPIO_NUM_12;
constexpr uint32_t SAMPLE_RATE = 16000;
constexpr uint32_t SERIAL_BAUD = 921600;
constexpr int I2S_TO_PCM_SHIFT = 16;
constexpr char STREAM_MAGIC[] = "NCAP";
constexpr char STREAM_ERROR[] = "ERRO";
constexpr uint8_t START_COMMAND = 'S';

i2s_chan_handle_t i2s_rx_channel = nullptr;
bool i2s_ready = false;
bool capture_started = false;

bool initialize_i2s() {
  i2s_chan_config_t channel_config =
      I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  if (i2s_new_channel(&channel_config, nullptr, &i2s_rx_channel) != ESP_OK) {
    return false;
  }

  i2s_std_config_t config = {};
  config.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE);
  config.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_32BIT,
      I2S_SLOT_MODE_MONO);
  config.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
  config.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  config.gpio_cfg.bclk = PIN_SCK;
  config.gpio_cfg.ws = PIN_WS;
  config.gpio_cfg.dout = I2S_GPIO_UNUSED;
  config.gpio_cfg.din = PIN_SD;

  if (i2s_channel_init_std_mode(i2s_rx_channel, &config) != ESP_OK) {
    return false;
  }
  return i2s_channel_enable(i2s_rx_channel) == ESP_OK;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);
  i2s_ready = initialize_i2s();
}

void loop() {
  if (!i2s_ready) {
    Serial.write(STREAM_ERROR, sizeof(STREAM_ERROR) - 1);
    delay(500);
    return;
  }

  if (!capture_started) {
    while (Serial.available() > 0) {
      if (Serial.read() == START_COMMAND) {
        Serial.write(STREAM_MAGIC, sizeof(STREAM_MAGIC) - 1);
        capture_started = true;
        break;
      }
    }
    delay(5);
    return;
  }

  int32_t raw[320];
  int16_t pcm[320];
  size_t bytes_read = 0;
  if (i2s_channel_read(
          i2s_rx_channel,
          raw,
          sizeof(raw),
          &bytes_read,
          portMAX_DELAY) != ESP_OK) {
    return;
  }
  const size_t samples = bytes_read / sizeof(raw[0]);

  for (size_t index = 0; index < samples; ++index) {
    const int32_t value = raw[index] >> I2S_TO_PCM_SHIFT;
    pcm[index] = static_cast<int16_t>(value);
  }

  Serial.write(
      reinterpret_cast<const uint8_t*>(pcm),
      samples * sizeof(pcm[0]));
}
