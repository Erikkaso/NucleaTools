# INMP441 dataset capture

Este e um sketch Arduino separado para gravar o dataset pelo cabo serial.
Ele substitui o firmware ESP-IDF gravado na placa e nao executa wakeword,
Wi-Fi, envio HTTP ou animacoes. Para voltar ao detector, regrave o firmware
com `idf.py -p COM9 flash monitor` na pasta `esp32_wakeword`.

## Ligacao deste sketch

| INMP441 | ESP32-S3 |
| --- | --- |
| VDD | 3.3 V |
| GND | GND |
| L/R | GND, canal esquerdo |
| SCK/BCLK | GPIO 11 |
| WS | GPIO 10 |
| SD | GPIO 12 |

Esses pinos diferem dos 4/5/6 usados pelo firmware com visor. Se o microfone
estiver em 4/5/6, ajuste `PIN_SCK`, `PIN_WS` e `PIN_SD` no sketch antes de
enviar, ou mude os fios com a placa desligada. Desconecte a tela quando usar
11/10/12: esses GPIOs tambem sao usados pelo visor.

## Gravar

1. Abra `inmp441_serial_capture/inmp441_serial_capture.ino` na Arduino IDE
   e envie para o ESP32-S3.
2. Feche o Serial Monitor, que nao pode compartilhar a porta.
3. Na raiz do repositorio (que contem `wake-word`), ative o ambiente Python,
   instale `pyserial` se necessario e execute:

```powershell
python -m pip install pyserial
python wake-word/esp32_wakeword/tools/inmp441_capture/record_inmp441.py --port COM9
```

O arquivo WAV mono PCM 16 kHz e 16-bit sera salvo em
`wake-word/dataset/inmp441_v1/continuous/`. A gravacao continua ate `Ctrl+C`.

O programa solicita explicitamente o inicio da transmissao ao ESP, portanto nao
e necessario pressionar RST depois de abri-lo. Se o I2S nao iniciar, o ESP
responde `ERRO` e o script informa a falha sem aguardar timeout.

Para escolher o destino:

```powershell
python wake-word/esp32_wakeword/tools/inmp441_capture/record_inmp441.py --port COM9 --output wake-word/dataset/inmp441_v1/positive/sessao_001.wav
```

A velocidade serial padrao e 921600 baud no sketch e no script. Nao altere
somente um dos dois. Se a porta retornar acesso negado, feche o Serial Monitor
da Arduino IDE e qualquer monitor ESP-IDF antes de iniciar a gravacao.
