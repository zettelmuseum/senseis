#!/usr/bin/env python3
"""Measure real SGF compression on a small prefix of the snapshot archive."""
from __future__ import annotations

import argparse
import json
import tarfile
import time
import zlib
from pathlib import Path


def benchmark(archive: Path, limit: int = 500) -> dict:
    samples = 0
    eligible = 0
    raw_bytes = 0
    packed1_bytes = 0
    packed6_bytes = 0
    started = time.perf_counter()
    time1 = 0.0
    time6 = 0.0

    with tarfile.open(archive, mode="r|bz2") as tar:
        for member in tar:
            if not member.isfile() or not member.name.lower().endswith(".sgf"):
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            with source:
                data = source.read()
            samples += 1
            if len(data) < 256:
                if samples >= limit:
                    break
                continue
            eligible += 1
            raw_bytes += len(data)
            t = time.perf_counter()
            packed1 = zlib.compress(data, 1)
            time1 += time.perf_counter() - t
            t = time.perf_counter()
            packed6 = zlib.compress(data, 6)
            time6 += time.perf_counter() - t
            packed1_bytes += len(packed1)
            packed6_bytes += len(packed6)
            if samples >= limit:
                break

    elapsed = time.perf_counter() - started
    saving1 = 1.0 - packed1_bytes / raw_bytes if raw_bytes else 0.0
    saving6 = 1.0 - packed6_bytes / raw_bytes if raw_bytes else 0.0
    speed6 = raw_bytes / time6 / (1024 * 1024) if time6 else 0.0
    # Only enable SGF compression if it saves at least 10% on real data
    # and the measured compressor throughput is comfortably above 5 MiB/s.
    recommended = eligible > 0 and saving6 >= 0.10 and speed6 >= 5.0
    return {
        "samples": samples,
        "eligible_samples": eligible,
        "raw_bytes": raw_bytes,
        "zlib1_bytes": packed1_bytes,
        "zlib6_bytes": packed6_bytes,
        "zlib1_saving_percent": round(saving1 * 100, 2),
        "zlib6_saving_percent": round(saving6 * 100, 2),
        "zlib6_mib_per_second": round(speed6, 2),
        "elapsed_seconds": round(elapsed, 3),
        "recommended": recommended,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = benchmark(args.archive, max(1, args.limit))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
