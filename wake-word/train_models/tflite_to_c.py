
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import re


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bytes_to_c_array(
    data: bytes,
    bytes_per_line: int = 12,
) -> str:
    if bytes_per_line <= 0:
        raise ValueError("bytes_per_line precisa ser > 0")

    lines = []

    for start in range(0, len(data), bytes_per_line):
        chunk = data[start:start + bytes_per_line]
        rendered = ", ".join(
            f"0x{value:02x}"
            for value in chunk
        )
        lines.append("    " + rendered)

    return ",\n".join(lines)


def render_header(symbol: str) -> str:
    guard = symbol.upper() + "_H_"

    return (
        f"#ifndef {guard}\n"
        f"#define {guard}\n\n"
        "#ifdef __cplusplus\n"
        'extern "C" {\n'
        "#endif\n\n"
        f"extern const unsigned char {symbol}[];\n"
        f"extern const unsigned int {symbol}_len;\n\n"
        "#ifdef __cplusplus\n"
        "}\n"
        "#endif\n\n"
        f"#endif  // {guard}\n"
    )


def render_source(
    symbol: str,
    header_name: str,
    data: bytes,
) -> str:
    digest = sha256_hex(data)
    array_text = bytes_to_c_array(data)

    return (
        f'#include "{header_name}"\n\n'
        "#include <cstdint>\n\n"
        "// Modelo TFLite embutido.\n"
        f"// SHA-256 original: {digest}\n"
        f"// Tamanho original: {len(data)} bytes\n"
        f"alignas(16) const unsigned char {symbol}[] = {{\n"
        f"{array_text}\n"
        "};\n\n"
        f"const unsigned int {symbol}_len = {len(data)};\n"
    )


def extract_bytes_from_source(
    source_text: str,
    symbol: str,
) -> bytes:
    pattern = re.compile(
        rf"{re.escape(symbol)}\[\]\s*=\s*\{{(.*?)\}};",
        re.DOTALL,
    )

    match = pattern.search(source_text)

    if not match:
        raise RuntimeError(
            f"Array {symbol} não encontrado no .cc gerado."
        )

    values = re.findall(
        r"0x([0-9a-fA-F]{2})",
        match.group(1),
    )

    return bytes(
        int(value, 16)
        for value in values
    )


def validate_symbol(symbol: str) -> str:
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        symbol,
    ):
        raise ValueError(
            "Nome de símbolo C/C++ inválido: "
            f"{symbol!r}"
        )

    return symbol


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Converte um modelo .tflite em .h/.cc para "
            "embutir no firmware ESP32 e verifica que os "
            "bytes gerados são idênticos ao arquivo original."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "output_tflite_int8/nuclea_int8.tflite"
        ),
        help="Arquivo .tflite de entrada.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("esp32_model"),
        help="Diretório onde serão criados .h/.cc/manifest.json.",
    )

    parser.add_argument(
        "--symbol",
        default="nuclea_model",
        help="Nome do símbolo C/C++ do modelo.",
    )

    args = parser.parse_args()

    symbol = validate_symbol(args.symbol)

    if not args.input.exists():
        raise FileNotFoundError(
            f"Modelo não encontrado: {args.input}"
        )

    data = args.input.read_bytes()

    if not data:
        raise RuntimeError(
            "O arquivo .tflite está vazio."
        )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    header_name = f"{symbol}.h"
    source_name = f"{symbol}.cc"

    header_path = args.output_dir / header_name
    source_path = args.output_dir / source_name
    manifest_path = args.output_dir / "model_manifest.json"

    header_text = render_header(symbol)

    source_text = render_source(
        symbol=symbol,
        header_name=header_name,
        data=data,
    )

    header_path.write_text(
        header_text,
        encoding="utf-8",
        newline="\n",
    )

    source_path.write_text(
        source_text,
        encoding="utf-8",
        newline="\n",
    )

    recovered = extract_bytes_from_source(
        source_text,
        symbol,
    )

    same_bytes = recovered == data

    if not same_bytes:
        raise RuntimeError(
            "Falha na verificação: o array C gerado "
            "não é idêntico ao .tflite original."
        )

    original_sha = sha256_hex(data)
    recovered_sha = sha256_hex(recovered)

    manifest = {
        "input_model": str(args.input),
        "header": str(header_path),
        "source": str(source_path),
        "symbol": symbol,
        "size_bytes": len(data),
        "sha256_original": original_sha,
        "sha256_recovered": recovered_sha,
        "byte_for_byte_match": same_bytes,
        "alignment_bytes": 16,
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("TFLITE -> C/C++")
    print("=" * 72)

    print(f"Entrada:   {args.input}")
    print(
        f"Tamanho:   {len(data)} bytes "
        f"({len(data) / 1024:.2f} KiB)"
    )
    print(f"SHA-256:   {original_sha}")

    print()
    print(f"Header:    {header_path}")
    print(f"Source:    {source_path}")
    print(f"Manifest:  {manifest_path}")

    print()
    print("Verificação byte-a-byte: OK")
    print(f"SHA-256 reconstruído:    {recovered_sha}")

    print()
    print(f"Símbolo do modelo:       {symbol}")
    print(f"Tamanho em C/C++:        {symbol}_len")


if __name__ == "__main__":
    main()
