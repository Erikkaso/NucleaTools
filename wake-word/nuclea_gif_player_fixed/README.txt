NUCLEA GIF PLAYER - ESP32-S3 + ST7789V2

Esta pasta conserva o player Arduino independente e os GIFs usados pelo
firmware ESP-IDF em ../esp32_wakeword.

INTEGRACAO COM WAKEWORD:
Use ../esp32_wakeword e siga ../README.md. O build ESP-IDF gera e grava
LittleFS com os tres GIFs; nao grave este sketch por cima do firmware.
A tela usa GPIOs 8 a 12. Com o visor integrado, o INMP441 muda para
SCK/BCLK=4, WS=5 e SD=6. E necessario mudar fisicamente esses tres fios.
Para testar so o microfone, desative NUCLEA_DISPLAY_ENABLED no menuconfig
do ESP-IDF, confira os GPIOs e regrave. Nao e necessario gravar este sketch.

Arquivos atuais (280x240), lista completa em ../README.md:
- idle.gif: 97 frames, 8,08 segundos (substitui nuclea-blink.gif).
- sleep.gif: 70 frames, 5,83 segundos.
- wake.gif: 53 frames, 2,21 segundos.
- wake-open.gif: reverso de wake.gif, gerado por
  ../esp32_wakeword/tools/reverse_gif.py.
O sketch Arduino abaixo ainda procura nuclea-blink.gif.

PLAYER ARDUINO INDEPENDENTE:
O sketch alterna estados por tempo, sem detectar wakeword. Seu cache RLE
experimental nao e o renderer utilizado no firmware ESP-IDF.

IMPORTANTE:
O upload normal do sketch NAO envia os arquivos data/*.gif para a flash.
Voce precisa fazer um segundo upload do filesystem LittleFS.

Arduino IDE:
1. Board: ESP32S3 Dev Module
2. Flash Size: 16MB (128Mb)
3. Mantenha partitions.csv na mesma pasta do .ino
4. Instale:
   - Adafruit GFX Library
   - Adafruit ST7735 and ST7789 Library
   - AnimatedGIF (Larry Bank)
5. Faça Upload normal do sketch.
6. Instale o plugin Arduino LittleFS Upload para Arduino IDE 2.x.
7. Feche o Serial Monitor.
8. Ctrl+Shift+P -> Upload LittleFS to Pico/ESP8266/ESP32
9. Reinicie a placa.
10. Abra Serial Monitor em 115200.

A pasta deve ficar:
nuclea_gif_player_fixed/
  nuclea_gif_player_fixed.ino
  partitions.csv
  data/
    nuclea-blink.gif
    wake.gif
    sleep.gif

Pinagem:
SCL -> GPIO 10
SDA -> GPIO 11
CS  -> GPIO 12
DC  -> GPIO 9
RES -> GPIO 8
VCC -> 3.3 V
BL/BLK -> 3.3 V
GND -> GND

Com o firmware atual, ligue todos esses sinais. VCC e BL podem compartilhar
a alimentacao, e o GND deve ser comum ao ESP32, tela e microfone.
