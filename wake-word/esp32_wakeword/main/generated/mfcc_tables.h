#ifndef MFCC_TABLES_H_
#define MFCC_TABLES_H_

#include "stdint.h"

#define MFCC_N_FFT 512
#define MFCC_WIN_LENGTH 400
#define MFCC_N_MELS 40
#define MFCC_N_MFCC 13
#define MFCC_FRAMES 49

extern const float mfcc_window[512];
extern const float mfcc_mel_basis[10280];
extern const float mfcc_dct[520];
extern const uint16_t mfcc_bit_reverse[512];
extern const float mfcc_fft_cos[256];
extern const float mfcc_fft_sin[256];
extern const int16_t test_pcm_audio[16000];
extern const int8_t expected_mfcc_output[637];

#endif // MFCC_TABLES_H_
