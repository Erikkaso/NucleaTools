#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <AnimatedGIF.h>
#include <LittleFS.h>

// Fiação já testada com seu ESP32-S3 GOOUUU.
#define TFT_SCLK 10
#define TFT_MOSI 11
#define TFT_CS   12
#define TFT_DC    9
#define TFT_RST   8

constexpr int W = 280;
constexpr int H = 240;
constexpr size_t PIXELS = (size_t)W * H;
constexpr uint32_t TEMPO_ACORDADO_MS = 4000;
constexpr uint32_t TEMPO_DORMINDO_MS = 4000;

// Limite da memória utilizada para gravar os frames da transição.
// NÃO grava os frames de volta na flash; utiliza PSRAM.
constexpr size_t CACHE_LIMITE = 5UL * 1024UL * 1024UL;
constexpr int MAX_FRAMES_CACHE = 256;

Adafruit_ST7789 tft(TFT_CS, TFT_DC, TFT_RST);
AnimatedGIF gif;
File gifFile;

uint16_t lineBuffer[W];
uint16_t *canvas = nullptr;      // RGB565, imagem final de cada frame
uint8_t *cache = nullptr;        // frames da transição compactados em PSRAM
size_t cacheCapacity = 0;
size_t cacheUsed = 0;

size_t frameOffset[MAX_FRAMES_CACHE];
size_t frameSize[MAX_FRAMES_CACHE];
uint16_t frameDelay[MAX_FRAMES_CACHE];
int cacheCount = 0;
uint32_t captureStride = 1;
bool reversePronto = false;

// ======== Acesso ao GIF no LittleFS ========

void *GIFOpenFile(const char *fname, int32_t *pSize) {
  gifFile = LittleFS.open(fname, "r");
  if (!gifFile) {
    *pSize = 0;
    return nullptr;
  }

  *pSize = gifFile.size();
  return &gifFile;
}

void GIFCloseFile(void *pHandle) {
  File *f = static_cast<File *>(pHandle);
  if (f) f->close();
}

int32_t GIFReadFile(GIFFILE *pFile, uint8_t *pBuf, int32_t length) {
  File *f = static_cast<File *>(pFile->fHandle);
  if (!f) return 0;

  int32_t available = pFile->iSize - pFile->iPos;
  if (length > available) length = available;
  if (length <= 0) return 0;

  int32_t n = f->read(pBuf, length);
  pFile->iPos = f->position();
  return n;
}

int32_t GIFSeekFile(GIFFILE *pFile, int32_t pos) {
  File *f = static_cast<File *>(pFile->fHandle);
  if (!f) return 0;

  f->seek(pos);
  pFile->iPos = f->position();
  return pFile->iPos;
}

// Atualiza a tela e o canvas. O canvas serve para guardar um frame
// COMPLETO da animação, mesmo se o GIF só desenhar partes que mudaram.
void GIFDraw(GIFDRAW *pDraw) {
  int x = pDraw->iX;
  int y = pDraw->iY + pDraw->y;
  int width = pDraw->iWidth;
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  if (x + width > W) width = W - x;
  if (width <= 0) return;

  uint16_t *dest = canvas + (size_t)y * W + x;
  uint8_t *src = pDraw->pPixels;
  uint16_t *palette = pDraw->pPalette;

  for (int i = 0; i < width; ++i) {
    uint8_t index = src[i];

    // Transparência: preservar o pixel da imagem anterior.
    // Disposal=2: usar a cor de fundo fornecida pelo decoder.
    if (pDraw->ucHasTransparency && index == pDraw->ucTransparent) {
      if (pDraw->ucDisposalMethod == 2) {
        dest[i] = palette[pDraw->ucBackground];
      }
    } else {
      dest[i] = palette[index];
    }
    lineBuffer[i] = dest[i];
  }

  tft.drawRGBBitmap(x, y, lineBuffer, width, 1);
}

// ======== Cache dos frames do wake.gif na PSRAM ========

// Cada frame é armazenado de um destes modos:
// 0 + pixels RGB565 (sem compressão)
// 1 + sequências de [quantidade (1 byte), cor RGB565 (2 bytes)]
// A compressão RLE mantém EXATAMENTE as cores RGB565.
size_t medirFrameCompactado() {
  size_t runs = 0;
  for (size_t p = 0; p < PIXELS;) {
    uint16_t cor = canvas[p];
    size_t n = 1;
    while (n < 255 && p + n < PIXELS && canvas[p + n] == cor) ++n;
    p += n;
    ++runs;
  }
  size_t rleBytes = 1 + runs * 3;
  size_t rawBytes = 1 + PIXELS * sizeof(uint16_t);
  return (rleBytes < rawBytes) ? rleBytes : rawBytes;
}

void reduzirCachePelaMetade() {
  size_t novoUsed = 0;
  int novoCount = 0;

  for (int i = 0; i < cacheCount; i += 2) {
    memmove(cache + novoUsed, cache + frameOffset[i], frameSize[i]);
    frameOffset[novoCount] = novoUsed;
    frameSize[novoCount] = frameSize[i];
    frameDelay[novoCount] = frameDelay[i];
    novoUsed += frameSize[i];
    ++novoCount;
  }

  cacheUsed = novoUsed;
  cacheCount = novoCount;
  captureStride *= 2;
  Serial.printf("Cache otimizado: guardando 1 a cada %lu frames\n",
                (unsigned long)captureStride);
}

bool guardarFrame(uint32_t numero, int delayMs, bool forcar = false) {
  if (!forcar && numero % captureStride != 0) return true;

  size_t bytes = medirFrameCompactado();

  while ((cacheUsed + bytes > cacheCapacity ||
          cacheCount >= MAX_FRAMES_CACHE) && cacheCount > 1) {
    reduzirCachePelaMetade();
  }

  // A compactação pode ter mudado o intervalo de captura.
  if (!forcar && numero % captureStride != 0) return true;
  if (cacheUsed + bytes > cacheCapacity || cacheCount >= MAX_FRAMES_CACHE) {
    Serial.println("Aviso: limite de PSRAM do cache atingido");
    return false;
  }

  size_t inicio = cacheUsed;
  uint8_t *dst = cache + cacheUsed;
  size_t rawBytes = 1 + PIXELS * sizeof(uint16_t);

  if (bytes == rawBytes) {
    *dst++ = 0;
    memcpy(dst, canvas, PIXELS * sizeof(uint16_t));
  } else {
    *dst++ = 1;
    for (size_t p = 0; p < PIXELS;) {
      uint16_t cor = canvas[p];
      uint8_t n = 1;
      while (n < 255 && p + n < PIXELS && canvas[p + n] == cor) ++n;
      *dst++ = n;
      *dst++ = (uint8_t)(cor & 0xFF);
      *dst++ = (uint8_t)(cor >> 8);
      p += n;
    }
  }

  frameOffset[cacheCount] = inicio;
  frameSize[cacheCount] = bytes;
  frameDelay[cacheCount] = delayMs > 0 ? (uint16_t)delayMs : 40;
  cacheUsed += bytes;
  ++cacheCount;
  return true;
}

void restaurarFrame(int indice) {
  const uint8_t *src = cache + frameOffset[indice];

  if (*src++ == 0) {
    memcpy(canvas, src, PIXELS * sizeof(uint16_t));
  } else {
    size_t p = 0;
    const uint8_t *fim = cache + frameOffset[indice] + frameSize[indice];
    while (p < PIXELS && src + 3 <= fim) {
      uint8_t qtd = *src++;
      uint16_t cor = src[0] | ((uint16_t)src[1] << 8);
      src += 2;
      for (int j = 0; j < qtd && p < PIXELS; j++) canvas[p++] = cor;
    }
  }

  tft.drawRGBBitmap(0, 0, canvas, W, H);
}

// ======== Reprodução dos arquivos ========

bool tocarUmaVez(const char *arquivo, bool capturar = false) {
  Serial.printf("Tocando: %s\n", arquivo);

  if (!gif.open(arquivo, GIFOpenFile, GIFCloseFile, GIFReadFile,
                GIFSeekFile, GIFDraw)) {
    Serial.printf("Erro abrindo %s\n", arquivo);
    return false;
  }

  int estado;
  int atrasoMs = 40;
  uint32_t numero = 0;

  do {
    atrasoMs = 40;
    estado = gif.playFrame(true, &atrasoMs);
    if (capturar) guardarFrame(numero, atrasoMs);
    ++numero;
    yield();
  } while (estado == 1);

  gif.close();

  // Inclui a pose final de olhos fechados, mesmo se houve amostragem.
  if (capturar && numero > 0 && (numero - 1) % captureStride != 0) {
    guardarFrame(numero - 1, atrasoMs, true);
  }

  if (capturar) {
    reversePronto = cacheCount > 1;
    Serial.printf("Transicao: %lu frames processados, %d guardados; "
                  "cache %lu KB\n",
                  (unsigned long)numero, cacheCount,
                  (unsigned long)(cacheUsed / 1024));
  }
  return true;
}

void tocarPorTempo(const char *arquivo, uint32_t tempo) {
  uint32_t inicio = millis();
  do {
    if (!tocarUmaVez(arquivo)) break;
  } while ((uint32_t)(millis() - inicio) < tempo);
}

void tocarWakeReverso() {
  if (!reversePronto) {
    Serial.println("Reverse indisponivel: cache nao foi criado.");
    return;
  }

  Serial.println("Wake ao contrario (cache em PSRAM)");
  for (int i = cacheCount - 1; i >= 0; --i) {
    uint32_t inicio = millis();
    restaurarFrame(i);

    uint32_t desejado = (uint32_t)frameDelay[i] * captureStride;
    if (desejado > 160) desejado = 160;
    uint32_t gasto = millis() - inicio;
    if (gasto < desejado) delay(desejado - gasto);
    yield();
  }
}

// ======== Inicialização ========

void setup() {
  Serial.begin(115200);
  delay(800);

  SPI.begin(TFT_SCLK, -1, TFT_MOSI, TFT_CS);
  tft.init(240, 280);
  tft.setRotation(1);
  tft.fillScreen(ST77XX_BLACK);

  if (!psramFound()) {
    Serial.println("ERRO: PSRAM nao detectada!");
    Serial.println("Ferramentas > PSRAM > OPI PSRAM");
    while (true) delay(1000);
  }

  canvas = (uint16_t *)ps_malloc(PIXELS * sizeof(uint16_t));
  if (!canvas) {
    Serial.println("ERRO: sem PSRAM para o canvas");
    while (true) delay(1000);
  }
  memset(canvas, 0, PIXELS * sizeof(uint16_t));

  size_t livre = ESP.getFreePsram();
  if (livre > 512UL * 1024UL) {
    cacheCapacity = livre - 512UL * 1024UL;
    if (cacheCapacity > CACHE_LIMITE) cacheCapacity = CACHE_LIMITE;
    cache = (uint8_t *)ps_malloc(cacheCapacity);
  }

  if (!cache) {
    Serial.println("ERRO: nao foi possivel alocar cache na PSRAM");
    while (true) delay(1000);
  }

  if (!LittleFS.begin(false)) {
    Serial.println("ERRO: LittleFS nao montou");
    while (true) delay(1000);
  }

  const char *arquivos[] = {
    "/nuclea-blink.gif",
    "/wake.gif",
    "/sleep.gif"
  };

  for (const char *f : arquivos) {
    if (!LittleFS.exists(f)) {
      Serial.printf("ERRO: arquivo ausente %s\n", f);
      tft.fillScreen(ST77XX_RED);
      tft.setTextColor(ST77XX_WHITE);
      tft.setTextSize(2);
      tft.setCursor(10, 110);
      tft.println("GIF ausente");
      while (true) delay(1000);
    }
  }

  gif.begin(LITTLE_ENDIAN_PIXELS);
  Serial.printf("Pronto! PSRAM cache: %lu KB\n",
                (unsigned long)(cacheCapacity / 1024));
}

void loop() {
  // Acordado, piscando durante um periodo.
  tocarPorTempo("/nuclea-blink.gif", TEMPO_ACORDADO_MS);

  // Fecha os olhos: reproduz uma vez.
  // Apenas na primeira execucao guarda os frames para o reverse.
  tocarUmaVez("/wake.gif", !reversePronto);

  // Dormindo durante um periodo.
  tocarPorTempo("/sleep.gif", TEMPO_DORMINDO_MS);

  // Reabre os olhos sem precisar de wake-reverse.gif.
  tocarWakeReverso();
}
