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
    bool LastFrame() const { return opened_ && !more_; }
    bool Info(GIFINFO* info) { return opened_ && gif_.getInfo(info); }
    const uint16_t* Canvas() const { return canvas_; }
    // Bounding box (x1/y1 exclusive) of pixels that may differ from the previous Next().
    void Dirty(int* x0, int* y0, int* x1, int* y1) const { *x0 = dx0_; *y0 = dy0_; *x1 = dx1_; *y1 = dy1_; }
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
    int dx0_ = 0, dy0_ = 0, dx1_ = kWidth, dy1_ = kHeight;
    bool fresh_ = true;
    int x_ = 0, y_ = 0, width_ = 0, height_ = 0;
};
