#include "mfcc.h"

#include <algorithm>
#include <cmath>

#include "esp_log.h"

namespace {

constexpr float kPcm16Scale = 1.0f / 32768.0f;
constexpr float kPowerToDbAmin = 1.0e-10f;
constexpr float kPowerToDbTopDb = 80.0f;
constexpr int kFftBins = (MFCC_N_FFT / 2) + 1;

// A inferencia e serial; buffers estaticos evitam alocacao no caminho de audio.
static float s_real[MFCC_N_FFT];
static float s_imag[MFCC_N_FFT];
static float s_power[kFftBins];
static float s_mel_db[MFCC_N_MELS * MFCC_FRAMES];

void ForwardFft512(float* real, float* imag) {
    for (int i = 0; i < MFCC_N_FFT; ++i) {
        const int reversed = static_cast<int>(mfcc_bit_reverse[i]);
        if (reversed > i) {
            std::swap(real[i], real[reversed]);
            std::swap(imag[i], imag[reversed]);
        }
    }

    for (int length = 2; length <= MFCC_N_FFT; length <<= 1) {
        const int half_length = length >> 1;
        const int twiddle_step = MFCC_N_FFT / length;

        for (int start = 0; start < MFCC_N_FFT; start += length) {
            for (int offset = 0; offset < half_length; ++offset) {
                const int twiddle_index = offset * twiddle_step;
                const float wr = mfcc_fft_cos[twiddle_index];
                const float wi = mfcc_fft_sin[twiddle_index];
                const int even_index = start + offset;
                const int odd_index = even_index + half_length;
                const float odd_real = real[odd_index];
                const float odd_imag = imag[odd_index];
                const float transformed_real = wr * odd_real - wi * odd_imag;
                const float transformed_imag = wr * odd_imag + wi * odd_real;
                const float even_real = real[even_index];
                const float even_imag = imag[even_index];

                real[even_index] = even_real + transformed_real;
                imag[even_index] = even_imag + transformed_imag;
                real[odd_index] = even_real - transformed_real;
                imag[odd_index] = even_imag - transformed_imag;
            }
        }
    }
}

int8_t QuantizeMfcc(float value, float quant_scale, int quant_zero_point) {
    const float transformed = value / quant_scale + static_cast<float>(quant_zero_point);
    const int quantized = static_cast<int>(std::nearbyintf(transformed));
    return static_cast<int8_t>(std::clamp(quantized, -128, 127));
}

}  // namespace

MFCC::MFCC() = default;
MFCC::~MFCC() = default;

bool MFCC::init() {
    initialized_ = true;
    return true;
}

bool MFCC::compute(const int16_t* pcm_data, int8_t* out_quantized,
                   float quant_scale, int quant_zero_point) {
    if (!initialized_ || pcm_data == nullptr || out_quantized == nullptr ||
        !std::isfinite(quant_scale) || quant_scale <= 0.0f) {
        return false;
    }

    constexpr int kHopLength = 320;
    float global_max_db = -INFINITY;
    for (int frame = 0; frame < MFCC_FRAMES; ++frame) {
        const int sample_offset = frame * kHopLength;
        for (int i = 0; i < MFCC_N_FFT; ++i) {
            s_real[i] = static_cast<float>(pcm_data[sample_offset + i]) *
                        kPcm16Scale * mfcc_window[i];
            s_imag[i] = 0.0f;
        }

        ForwardFft512(s_real, s_imag);

        for (int bin = 0; bin < kFftBins; ++bin) {
            s_power[bin] = s_real[bin] * s_real[bin] + s_imag[bin] * s_imag[bin];
        }

        for (int mel = 0; mel < MFCC_N_MELS; ++mel) {
            float mel_power = 0.0f;
            const float* filter = &mfcc_mel_basis[mel * kFftBins];
            for (int bin = 0; bin < kFftBins; ++bin) {
                mel_power += filter[bin] * s_power[bin];
            }
            const float db = 10.0f * std::log10f(std::max(kPowerToDbAmin, mel_power));
            s_mel_db[mel * MFCC_FRAMES + frame] = db;
            global_max_db = std::max(global_max_db, db);
        }
    }

    const float minimum_db = global_max_db - kPowerToDbTopDb;
    for (int frame = 0; frame < MFCC_FRAMES; ++frame) {
        for (int mel = 0; mel < MFCC_N_MELS; ++mel) {
            const int index = mel * MFCC_FRAMES + frame;
            s_mel_db[index] = std::max(s_mel_db[index], minimum_db);
        }

        for (int coefficient = 0; coefficient < MFCC_N_MFCC; ++coefficient) {
            float value = 0.0f;
            const float* dct_row = &mfcc_dct[coefficient * MFCC_N_MELS];
            for (int mel = 0; mel < MFCC_N_MELS; ++mel) {
                value += dct_row[mel] * s_mel_db[mel * MFCC_FRAMES + frame];
            }
            out_quantized[coefficient * MFCC_FRAMES + frame] =
                QuantizeMfcc(value, quant_scale, quant_zero_point);
        }
    }

    return true;
}

bool verify_mfcc_parity(float quant_scale, int quant_zero_point) {
    MFCC mfcc;
    if (!mfcc.init()) {
        return false;
    }

    int8_t generated_output[MFCC_N_MFCC * MFCC_FRAMES];
    if (!mfcc.compute(test_pcm_audio, generated_output, quant_scale, quant_zero_point)) {
        ESP_LOGE("MFCC", "Erro no calculo do MFCC de teste");
        return false;
    }

    int max_delta = 0;
    int mismatches = 0;
    for (int i = 0; i < MFCC_N_MFCC * MFCC_FRAMES; ++i) {
        const int difference = std::abs(generated_output[i] - expected_mfcc_output[i]);
        max_delta = std::max(max_delta, difference);
        if (difference > 1) {
            if (mismatches == 0) {
                ESP_LOGE("MFCC", "Primeira divergencia no indice %d: C++ = %d, Python = %d",
                         i, generated_output[i], expected_mfcc_output[i]);
            }
            ++mismatches;
        }
    }

    if (mismatches != 0) {
        ESP_LOGE("MFCC", "PARIDADE FALHOU: %d/%d coeficientes fora da tolerancia (Delta Max = %d)",
                 mismatches, MFCC_N_MFCC * MFCC_FRAMES, max_delta);
        return false;
    }

    ESP_LOGI("MFCC", "PARIDADE DSP APROVADA: %d coeficientes dentro de +/-1 INT8.",
             MFCC_N_MFCC * MFCC_FRAMES);
    return true;
}
