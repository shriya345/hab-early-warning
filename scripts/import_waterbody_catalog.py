"""Build a Karnataka-only SQLite catalog from official water-body census CSVs.

The source census can contain millions of rows. This importer streams the CSV,
keeps records with usable India coordinates, and builds an FTS5 name/state index.
It does not mark catalog records as eligible for CNN/LSTM predictions.
"""

import argparse
import csv
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_number(value):
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, nargs="+", help="One or more unzipped official census CSV files")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "data/lakes/karnataka_lakes.sqlite3")
    parser.add_argument("--id-column", help="Stable census water-body identifier (optional)")
    parser.add_argument("--name-column", required=True)
    parser.add_argument("--state-column", required=True)
    parser.add_argument("--latitude-column", required=True)
    parser.add_argument("--longitude-column", required=True)
    parser.add_argument("--area-column", help="Area column (optional)")
    parser.add_argument("--area-unit", choices=("ha", "km2"), default="ha")
    parser.add_argument("--type-column", help="Water-body type column (optional)")
    parser.add_argument("--source", default="First Census of Water Bodies, 2017-18", help="Catalog source and vintage")
    args = parser.parse_args()

    missing_paths = [path for path in args.input_csv if not path.is_file()]
    if missing_paths:
        parser.error(f"Input CSV files do not exist: {missing_paths}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".building")
    if temporary.exists():
        temporary.unlink()

    total = inserted = skipped = 0
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("CREATE TABLE waterbodies (lake_id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, area_ha REAL, body_type TEXT NOT NULL, catalog_source TEXT NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE waterbodies_fts USING fts5(lake_id UNINDEXED, name, state, body_type, tokenize='unicode61 remove_diacritics 2')")
            fts_insert = "INSERT INTO waterbodies_fts (lake_id, name, state, body_type) VALUES (?, ?, ?, ?)"

            for input_path in args.input_csv:
                with input_path.open("r", encoding="utf-8-sig", newline="") as source:
                    reader = csv.DictReader(source)
                    columns = set(reader.fieldnames or [])
                    required = [args.name_column, args.state_column, args.latitude_column, args.longitude_column]
                    optional = [x for x in (args.id_column, args.area_column, args.type_column) if x]
                    missing = [column for column in required + optional if column not in columns]
                    if missing:
                        parser.error(f"Columns missing from {input_path}: {missing}. Available columns: {sorted(columns)}")

                    for row in reader:
                        total += 1
                        name = (row.get(args.name_column) or "").strip()
                        state = (row.get(args.state_column) or "").strip()
                        latitude = parse_number(row.get(args.latitude_column))
                        longitude = parse_number(row.get(args.longitude_column))
                        supplied_id = (row.get(args.id_column) or "").strip() if args.id_column else ""
                        if state.casefold() != "karnataka" or latitude is None or longitude is None or not (6 <= latitude <= 38 and 68 <= longitude <= 98):
                            skipped += 1
                            continue
                        if supplied_id:
                            lake_id = supplied_id
                        else:
                            if not name:
                                skipped += 1
                                continue
                            fingerprint = f"{name.casefold()}|{state.casefold()}|{latitude:.6f}|{longitude:.6f}"
                            lake_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
                        if not name:
                            name = f"Unnamed water body {lake_id}"
                        area = parse_number(row.get(args.area_column)) if args.area_column else None
                        if area is not None and args.area_unit == "km2":
                            area *= 100
                        body_type = (row.get(args.type_column) or "").strip() if args.type_column else ""
                        cursor = db.execute("INSERT OR IGNORE INTO waterbodies VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (lake_id, name, state, latitude, longitude, area, body_type, args.source))
                        if cursor.rowcount:
                            db.execute(fts_insert, (lake_id, name, state, body_type))
                            inserted += 1
                        else:
                            skipped += 1
                        if total % 10000 == 0:
                            db.commit()
                            print(f"Read {total:,}; retained {inserted:,}; skipped {skipped:,}", file=sys.stderr)
            db.commit()
            db.execute("CREATE INDEX waterbodies_state_idx ON waterbodies(state)")
            db.commit()
        os.replace(temporary, args.output)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    print(f"Catalog built at {args.output}: {inserted:,} records retained from {total:,}; {skipped:,} skipped")


if __name__ == "__main__":
    main()
