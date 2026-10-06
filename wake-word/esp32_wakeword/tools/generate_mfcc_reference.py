import os
import pathlib
import numpy as np
import librosa
import scipy.fftpack
import scipy.signal
import scipy.io.wavfile as wav

# --- Constantes do Design Document ---
SR = 16000
N_FFT = 512
WIN_LENGTH = 400
HOP_LENGTH = 320
N_MELS = 40
N_MFCC = 13
FMIN = 20
FMAX = 7600
QUANT_SCALE = 3.209484815597534
QUANT_ZERO_POINT = 69


def build_dsp_tables():
    window = scipy.signal.get_window("hann", WIN_LENGTH, fftbins=True).astype(np.float32)
    pad_left = (N_FFT - WIN_LENGTH) // 2
    pad_right = N_FFT - WIN_LENGTH - pad_left
    centered_window = np.pad(window, (pad_left, pad_right), mode="constant").astype(np.float32)

    dct = scipy.fftpack.dct(
        np.eye(N_MELS, dtype=np.float32), type=2, norm="ortho", axis=0
    )[:N_MFCC].astype(np.float32)

    bit_reverse = np.empty(N_FFT, dtype=np.uint16)
    bits = int(np.log2(N_FFT))
    for value in range(N_FFT):
        reversed_value = 0
        for bit in range(bits):
            reversed_value = (reversed_value << 1) | ((value >> bit) & 1)
        bit_reverse[value] = reversed_value

    angles = -2.0 * np.pi * np.arange(N_FFT // 2, dtype=np.float32) / float(N_FFT)
    return centered_window, dct, bit_reverse, np.cos(angles).astype(np.float32), np.sin(angles).astype(np.float32)


def _format_float(values):
    literals = []
    for value in np.asarray(values).reshape(-1):
        literal = f"{float(value):.9g}"
        if "." not in literal and "e" not in literal and "E" not in literal:
            literal += ".0"
        literals.append(f"{literal}f")
    return ", ".join(literals)


def _format_int(values):
    return ", ".join(str(int(value)) for value in np.asarray(values).reshape(-1))


def quantize_mfcc(mfcc, quant_scale, quant_zero_point):
    if not np.isfinite(quant_scale) or quant_scale <= 0:
        raise ValueError("quant_scale deve ser positivo")
    return np.clip(
        np.round(mfcc / quant_scale + quant_zero_point),
        -128,
        127,
    ).astype(np.int8)

def process_audio(audio_path, quant_scale=QUANT_SCALE, quant_zero_point=QUANT_ZERO_POINT):
    # 1. Carregar áudio
    sr, y = wav.read(audio_path)
    if sr != SR:
        raise ValueError(f"Sample rate deve ser {SR}, mas o arquivo possui {sr}")
    
    # Tratar amostras de 32-bit do I2S (INMP441) convertendo para PCM16
    if y.dtype == np.int32:
        y_16 = (y >> 16).astype(np.int16)
    elif y.dtype == np.float32 or y.dtype == np.float64:
        y_16 = np.clip(y * 32767.0, -32768, 32767).astype(np.int16)
    else:
        y_16 = y.astype(np.int16)
        
    y_16 = y_16[:SR] # Garante exatamente 16.000 amostras (1 segundo)
    
    # Normalizar PCM16 para float32 (-1.0 a 1.0) para o librosa
    y_float = y_16.astype(np.float32) / 32768.0
    
    # 2. Espectrograma (n_fft=512, win=400, hop=320, center=False)
    D = librosa.stft(y_float, n_fft=N_FFT, hop_length=HOP_LENGTH, 
                     win_length=WIN_LENGTH, window='hann', center=False)
    
    # 3. Espectro de Potência
    power_spectrogram = np.abs(D)**2
    
    # 4. Filtros Mel (Slaney-normalized)
    mel_basis = librosa.filters.mel(sr=SR, n_fft=N_FFT, n_mels=N_MELS, 
                                    fmin=FMIN, fmax=FMAX, norm='slaney')
    mel_spectrogram = np.dot(mel_basis, power_spectrogram)
    
    # 5. Converter para dB usando o maximo global da janela, como no treinamento.
    mel_db = librosa.power_to_db(
        mel_spectrogram,
        ref=1.0,
        amin=1e-10,
        top_db=80,
    )
    
    # 6. DCT-II Orthonormal
    mfcc = scipy.fftpack.dct(mel_db, type=2, axis=0, norm='ortho')[:N_MFCC]
    
    # 7. Quantização INT8
    mfcc_quantized = quantize_mfcc(mfcc, quant_scale, quant_zero_point)
    
    return y_16, mel_basis, mfcc_quantized

def generate_c_arrays(pcm_data, mel_basis, mfcc_quantized, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    window, dct, bit_reverse, fft_cos, fft_sin = build_dsp_tables()
    
    h_code = f"""#ifndef MFCC_TABLES_H_
#define MFCC_TABLES_H_

#include "stdint.h"

#define MFCC_N_FFT {N_FFT}
#define MFCC_WIN_LENGTH {WIN_LENGTH}
#define MFCC_N_MELS {N_MELS}
#define MFCC_N_MFCC {N_MFCC}
#define MFCC_FRAMES {mfcc_quantized.shape[1]}

extern const float mfcc_window[{N_FFT}];
extern const float mfcc_mel_basis[{N_MELS * (N_FFT // 2 + 1)}];
extern const float mfcc_dct[{N_MFCC * N_MELS}];
extern const uint16_t mfcc_bit_reverse[{N_FFT}];
extern const float mfcc_fft_cos[{N_FFT // 2}];
extern const float mfcc_fft_sin[{N_FFT // 2}];
extern const int16_t test_pcm_audio[{len(pcm_data)}];
extern const int8_t expected_mfcc_output[{N_MFCC * mfcc_quantized.shape[1]}];

#endif // MFCC_TABLES_H_
"""

    cc_code = f"""#include "mfcc_tables.h"

const float mfcc_window[{N_FFT}] = {{
    {_format_float(window)}
}};

const float mfcc_mel_basis[{N_MELS * (N_FFT // 2 + 1)}] = {{
    {_format_float(mel_basis)}
}};

const float mfcc_dct[{N_MFCC * N_MELS}] = {{
    {_format_float(dct)}
}};

const uint16_t mfcc_bit_reverse[{N_FFT}] = {{
    {_format_int(bit_reverse)}
}};

const float mfcc_fft_cos[{N_FFT // 2}] = {{
    {_format_float(fft_cos)}
}};

const float mfcc_fft_sin[{N_FFT // 2}] = {{
    {_format_float(fft_sin)}
}};

const int16_t test_pcm_audio[{len(pcm_data)}] = {{
    {_format_int(pcm_data)}
}};

const int8_t expected_mfcc_output[{N_MFCC * mfcc_quantized.shape[1]}] = {{
    {_format_int(mfcc_quantized)}
}};
"""

    with open(os.path.join(output_dir, "mfcc_tables.h"), "w") as f:
        f.write(h_code)
        
    with open(os.path.join(output_dir, "mfcc_tables.cc"), "w") as f:
        f.write(cc_code)
        
    print(f"Arquivos C gerados com sucesso em {output_dir}")

if __name__ == "__main__":
    script_dir = pathlib.Path(__file__).resolve().parent
    audio_path = script_dir / "inmp441_capture.wav"
    output_dir = script_dir.parent / "main" / "generated"
    
    pcm_data, mel_basis, mfcc_quantized = process_audio(audio_path)
    generate_c_arrays(pcm_data, mel_basis, mfcc_quantized, output_dir)
