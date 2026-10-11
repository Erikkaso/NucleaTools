#pragma once
#include "AnimatedGIF.h"

class GifAnimation {
public:
    static constexpr int kWidth = 280;
    static constexpr int kHeight = 240;
    static constexpr size_t kPixels = kWidth * kHeight;
    static constexpr size_t kFrameBytes = kPixels * sizeof(uint16_t);
    bool Init();
    bool Open(const char* path);
    void Close();
    bool Next(int* delay_ms);
    bool Info(GIFINFO* info) { return opened_ && gif_.getInfo(info); }
    const uint16_t* Canvas() const { return canvas_; }
private:
    static void* OpenFile(const char* path, int32_t* size);
    static void CloseFile(void* handle);
    static int32_t ReadFile(GIFFILE* file, uint8_t* buffer, int32_t size);
    static int32_t SeekFile(GIFFILE* file, int32_t position);
    static void Draw(GIFDRAW* row);
    AnimatedGIF gif_;
    uint16_t* canvas_ = nullptr;
    uint16_t* restore_ = nullptr;
    bool opened_ = false;
    bool more_ = false;
    bool drawn_ = false;
    bool first_frame_ = true;
    uint16_t background_ = 0;
    int disposal_ = 0;
    int x_ = 0, y_ = 0, width_ = 0, height_ = 0;
};
