#include "gif_animation.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <limits>
#include "esp_heap_caps.h"

bool GifAnimation::Init() {
    canvas_ = static_cast<uint16_t*>(heap_caps_calloc(1, kFrameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    restore_ = static_cast<uint16_t*>(heap_caps_malloc(kFrameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!canvas_ || !restore_) {
        heap_caps_free(canvas_);
        heap_caps_free(restore_);
        canvas_ = restore_ = nullptr;
        return false;
    }
    return true;
}

void* GifAnimation::OpenFile(const char* path, int32_t* size) {
    FILE* file = std::fopen(path, "rb");
    if (!file) return nullptr;
    if (std::fseek(file, 0, SEEK_END) != 0) { std::fclose(file); return nullptr; }
    const long length = std::ftell(file);
    if (length <= 0 || length > std::numeric_limits<int32_t>::max() ||
        std::fseek(file, 0, SEEK_SET) != 0) { std::fclose(file); return nullptr; }
    *size = static_cast<int32_t>(length);
    return file;
}

void GifAnimation::CloseFile(void* handle) { std::fclose(static_cast<FILE*>(handle)); }

int32_t GifAnimation::ReadFile(GIFFILE* file, uint8_t* buffer, int32_t size) {
    size = std::min(size, file->iSize - file->iPos);
    if (size <= 0) return 0;
    const size_t read = std::fread(buffer, 1, size, static_cast<FILE*>(file->fHandle));
    file->iPos += read;
    return read;
}

int32_t GifAnimation::SeekFile(GIFFILE* file, int32_t position) {
    if (position < 0 || position > file->iSize ||
        std::fseek(static_cast<FILE*>(file->fHandle), position, SEEK_SET) != 0) return -1;
    file->iPos = position;
    return position;
}

bool GifAnimation::Open(const char* path) {
    Close();
    gif_.begin(LITTLE_ENDIAN_PIXELS);
    opened_ = gif_.open(path, OpenFile, CloseFile, ReadFile, SeekFile, Draw);
    if (!opened_) return false;
    if (gif_.getCanvasWidth() != kWidth || gif_.getCanvasHeight() != kHeight) {
        Close();
        return false;
    }
    std::memset(canvas_, 0, kFrameBytes);
    disposal_ = 0;
    background_ = 0;
    first_frame_ = true;
    more_ = true;
    return true;
}

void GifAnimation::Close() {
    if (opened_) gif_.close();
    opened_ = more_ = false;
}

bool GifAnimation::Next(int* delay_ms) {
    if (!opened_ || !more_) return false;
    // Dispose the PREVIOUS frame before drawing the next one.
    if (disposal_ == 2) {
        for (int y = std::max(0, y_); y < std::min(kHeight, y_ + height_); ++y)
            std::fill(canvas_ + y * kWidth + std::max(0, x_),
                      canvas_ + y * kWidth + std::min(kWidth, x_ + width_), background_);
    } else if (disposal_ == 3) {
        std::memcpy(canvas_, restore_, kFrameBytes);
    }
    drawn_ = false;
    const int result = gif_.playFrame(false, delay_ms, this);
    more_ = result == 1;
    return result >= 0 && drawn_;
}

void GifAnimation::Draw(GIFDRAW* row) {
    auto* self = static_cast<GifAnimation*>(row->pUser);
    if (!self->drawn_) {
        if (row->ucIsGlobalPalette) self->background_ = row->pPalette[row->ucBackground];
        if (self->first_frame_) {
            std::fill(self->canvas_, self->canvas_ + kPixels, self->background_);
            self->first_frame_ = false;
        }
        if (row->ucDisposalMethod == 3)
            std::memcpy(self->restore_, self->canvas_, kFrameBytes);
        self->x_ = row->iX;
        self->y_ = row->iY;
        self->width_ = row->iWidth;
        self->height_ = row->iHeight;
        self->disposal_ = row->ucDisposalMethod;
        self->drawn_ = true;
    }
    const int y = row->iY + row->y;
    if (y < 0 || y >= kHeight) return;
    for (int i = std::max(0, -row->iX); i < row->iWidth && row->iX + i < kWidth; ++i) {
        const uint8_t index = row->pPixels[i];
        if (!row->ucHasTransparency || index != row->ucTransparent)
            self->canvas_[y * kWidth + row->iX + i] = row->pPalette[index];
    }
}
