"""Render a TensorFlow Lite model as a small C++ translation unit."""

from __future__ import annotations

import argparse
from pathlib import Path


def render_model_source(model_path: Path, symbol: str) -> tuple[str, str]:
    data = model_path.read_bytes()
    if not data:
        raise ValueError(f"Modelo TFLite vazio: {model_path}")

    header = f"""#pragma once

#include <cstddef>

extern const unsigned char {symbol}[];
extern const size_t {symbol}Size;
"""
    rows = [
        ", ".join(f"0x{byte:02x}" for byte in data[index : index + 12])
        for index in range(0, len(data), 12)
    ]
    formatted_data = ",\n    ".join(rows)
    source = f"""#include \"nuclea_model.h\"

alignas(16) const unsigned char {symbol}[] = {{
    {formatted_data}
}};

const size_t {symbol}Size = sizeof({symbol});
"""
    return header, source


def main() -> None:
    parser = argparse.ArgumentParser(description="Converte TFLite em fonte C++.")
    parser.add_argument("model", type=Path)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--symbol", default="kNucleaModelData")
    args = parser.parse_args()

    header, source = render_model_source(args.model, args.symbol)
    args.header.write_text(header, encoding="ascii", newline="\n")
    args.source.write_text(source, encoding="ascii", newline="\n")


if __name__ == "__main__":
    main()
