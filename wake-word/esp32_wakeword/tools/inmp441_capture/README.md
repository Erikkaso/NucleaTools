# INMP441 dataset capture

1. Abra `inmp441_serial_capture.ino` na Arduino IDE e envie para o ESP32-S3.
2. Feche o Serial Monitor, que nao pode compartilhar a porta.
3. No terminal da pasta `NucleaInterface`, ative o ambiente Python e execute:

```powershell
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

Os pinos usados sao BCLK GPIO11, WS GPIO10 e SD GPIO12.
