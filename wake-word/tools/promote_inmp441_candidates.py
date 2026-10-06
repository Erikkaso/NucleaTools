from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil

from prepare_inmp441_dataset import reviewed_candidate_files


def metadata_fieldnames(metadata_path: Path) -> list[str]:
    with metadata_path.open(encoding="utf-8-sig", newline="") as metadata:
        reader = csv.DictReader(metadata)
        fields = reader.fieldnames or []
    required = {"file", "group_id", "variant", "source_file"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"metadata.csv sem colunas: {', '.join(sorted(missing))}")
    return fields


def promote_candidates(
    review_dir: Path,
    speaker_dir: Path,
    session_id: str,
) -> list[Path]:
    candidates = reviewed_candidate_files(review_dir)
    if not candidates:
        raise ValueError("nenhum candidate_*.wav encontrado")

    clean_dir = speaker_dir / "clean"
    metadata_path = speaker_dir / "metadata.csv"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata nao encontrado: {metadata_path}")

    fieldnames = metadata_fieldnames(metadata_path)
    targets = [
        clean_dir / f"nuclea_{session_id}_{index:04d}.wav"
        for index, _ in enumerate(candidates, start=1)
    ]
    duplicates = [path for path in targets if path.exists()]
    if duplicates:
        raise FileExistsError(f"destino ja existe: {duplicates[0]}")

    clean_dir.mkdir(parents=True, exist_ok=True)
    for source, target in zip(candidates, targets):
        shutil.copy2(source, target)

    with metadata_path.open("a", newline="", encoding="utf-8") as metadata:
        writer = csv.DictWriter(metadata, fieldnames=fieldnames)
        for source, target in zip(candidates, targets):
            row = {field: "" for field in fieldnames}
            values = {
                "file": f"clean/{target.name}",
                "group_id": session_id,
                "variant": "clean",
                "source_file": source.as_posix(),
                "raw_duration_s": "1.0000",
                "reason": "reviewed_inmp441",
            }
            row.update({
                field: value
                for field, value in values.items()
                if field in row
            })
            writer.writerow(row)

    return targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promove candidatos INMP441 revisados para um falante real.",
    )
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--speaker-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    promoted = promote_candidates(
        args.review_dir,
        args.speaker_dir,
        args.session_id,
    )
    print(f"Promovidos: {len(promoted)}")
    print(f"Destino: {promoted[0].parent}")


if __name__ == "__main__":
    main()
