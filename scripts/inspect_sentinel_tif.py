#!/usr/bin/env python3
"""Inspect the exact raster input contract for a trained-model image."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to one archived model-input TIFF")
    args = parser.parse_args()
    if not args.path.is_file():
        raise SystemExit(f"TIFF file not found: {args.path}")

    with rasterio.open(args.path) as src:
        print(f"file: {args.path}")
        print(f"band count: {src.count}")
        print(f"dtype(s): {src.dtypes}")
        print(f"width x height: {src.width} x {src.height}")
        print(f"crs: {src.crs}")
        print(f"descriptions: {src.descriptions}")
        print(f"dataset tags: {src.tags()}")
        for index in range(1, src.count + 1):
            band = src.read(index, masked=True).astype(np.float32)
            values = band.compressed()
            if values.size == 0:
                print(f"band {index}: all pixels masked")
                continue
            print(
                f"band {index}: description={src.descriptions[index - 1]!r} "
                f"tags={src.tags(index)} min={float(values.min()):.3f} "
                f"max={float(values.max()):.3f} mean={float(values.mean()):.3f} "
                f"zero_frac={float((values == 0).mean()):.3f} "
                f"masked_frac={float(np.ma.getmaskarray(band).mean()):.3f}"
            )

    print("Required confirmation: map each file band to its Sentinel-2 band identity/order;")
    print("confirm the DN scale, cloud/nodata preparation, and crop/ROI against the model's training export.")


if __name__ == "__main__":
    main()
