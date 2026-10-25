"""Write a GIF with the composited frames of another GIF in reverse order.

The firmware plays wake.gif forward to close the eyes and the reversed copy to
open them, instead of caching every decoded frame in PSRAM. Requires Pillow.

    python esp32_wakeword/tools/reverse_gif.py \
        nuclea_gif_player_fixed/data/wake.gif nuclea_gif_player_fixed/data/wake-open.gif
"""
import argparse
from pathlib import Path

from PIL import Image, ImageSequence


def composited_frames(path):
    with Image.open(path) as gif:
        return [(frame.convert("RGB"), frame.info.get("duration", 100))
                for frame in ImageSequence.Iterator(gif)]


def timeline(frames):
    """Pixels and hold time per visible image; Pillow merges repeated frames on save."""
    merged = []
    for frame, duration in frames:
        pixels = frame.tobytes()
        if merged and merged[-1][0] == pixels:
            merged[-1][1] += duration
        else:
            merged.append([pixels, duration])
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.source.resolve():
        parser.error("output must differ from source")

    frames = composited_frames(args.source)[::-1]
    colors = sorted({color for frame, _ in frames for _, color in frame.getcolors(1 << 24)})
    if len(colors) > 256:
        raise SystemExit(f"{len(colors)} colors: cannot reverse without quantization loss")
    # Exact color lookup; Image.quantize() may pick a near palette entry.
    index = {color: i for i, color in enumerate(colors)}
    flat_palette = [channel for color in colors for channel in color]
    indexed = []
    for frame, _ in frames:
        image = Image.new("P", frame.size)
        image.putpalette(flat_palette)
        rgb = frame.tobytes()
        image.putdata([index[pixel] for pixel in zip(rgb[0::3], rgb[1::3], rgb[2::3])])
        indexed.append(image)
    indexed[0].save(args.output, save_all=True, append_images=indexed[1:],
                    duration=[duration for _, duration in frames], loop=0,
                    optimize=False, disposal=1)

    # Fail instead of shipping a lossy copy.
    written = composited_frames(args.output)
    if timeline(written) != timeline(frames):
        args.output.unlink()
        raise SystemExit("reversed GIF does not match the source frames")
    print(f"{args.output}: {len(written)} frames, {len(colors)} colors, "
          f"{args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
