#ifndef MFCC_H_
#define MFCC_H_

#include "cstdint"
#include "cstddef"
#include "generated/mfcc_tables.h"

class MFCC {
public:
    MFCC();
    ~MFCC();

    // Inicializa as tabelas de FFT da esp-dsp
    bool init();

    // Computa 49 frames de 13 coeficientes MFCC a partir de 16.000 amostras PCM16
    // out_quantized deve ter espaço para 13 * 49 = 637 bytes (int8_t)
    bool compute(const int16_t* pcm_data, int8_t* out_quantized,
                 float quant_scale, int quant_zero_point);

private:
    bool initialized_ = false;
};

// Função utilitária para testar a paridade do DSP no arranque
bool verify_mfcc_parity(float quant_scale, int quant_zero_point);

#endif // MFCC_H_
