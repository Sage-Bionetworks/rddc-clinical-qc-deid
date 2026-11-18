"""Build the screen_omop fixture batches from rddc-fhir-to-omop's output.

  python3 -I tests/screen_omop/make_batches.py OMOP_DIR   (needs pyarrow)
  python3 -I tests/screen_omop/make_batches.py --errors   (after the sidecars exist)

OMOP_DIR is rddc-fhir-to-omop's omop/ output (Parquet) for its 8-patient Synthea test batch
(tests/data/batch, the same synthetic data as tests/screen_fhir/dirty). Writes:

  dirty/omop/   the tables as deposited CSV (measurement as Parquet, observation gzipped,
                to cover the three readers). location keeps Synthea's street addresses and
                cities, provider and care_site their names and NPIs, device_exposure its
                production identifiers: the screen must quarantine it.
  clean/omop/   the same with those columns emptied and person_source_value replaced by a
                Research ID (RID-0001...): the screen must pass it.

The sidecars are written by `make fixtures` with rddc-sidecar. `--errors` then writes
dirty/_sidecar.errors.json: the dirty sidecar with a wrong md5 for omop/person.csv, so the
table fails intake and the run must fail.
"""

import csv
import gzip
import shutil
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLEAR = {
    "location": ["address_1", "address_2", "city", "county", "latitude", "longitude", "location_source_value"],
    "provider": ["provider_name", "npi", "dea", "provider_source_value", "year_of_birth"],
    "care_site": ["care_site_name", "care_site_source_value"],
    "device_exposure": ["production_id"],
}
PARQUET = {"measurement"}
GZIP = {"observation"}


def cell(v):
    return "" if v is None else str(v)


def write(table, rows, names, out):
    if table in PARQUET:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(rows), out / f"{table}.parquet")
        return
    path = out / (f"{table}.csv.gz" if table in GZIP else f"{table}.csv")
    with (gzip.open(path, "wt", newline="") if table in GZIP else open(path, "w", newline="")) as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(names)
        for r in rows:
            w.writerow([cell(r[n]) for n in names])


def main(src):
    import pyarrow.parquet as pq

    for kind in ("dirty", "clean"):
        out = HERE / kind / "omop"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
    rids = {}
    for f in sorted(Path(src).glob("*.parquet")):
        table = f.stem
        t = pq.read_table(f)
        names, rows = t.column_names, t.to_pylist()
        write(table, rows, names, HERE / "dirty" / "omop")
        clean = []
        for r in rows:
            r = dict(r)
            for c in CLEAR.get(table, []):
                if c in r:
                    r[c] = None
            if table == "person":
                r["person_source_value"] = rids.setdefault(r["person_source_value"], f"RID-{len(rids) + 1:04d}")
            clean.append(r)
        if table in PARQUET:
            # Keep the source schema, so emptied columns keep their types.
            import pyarrow as pa
            pq.write_table(pa.Table.from_pylist(clean, schema=t.schema), HERE / "clean" / "omop" / f"{table}.parquet")
        else:
            write(table, clean, names, HERE / "clean" / "omop")
    print(f"wrote {HERE / 'dirty'} and {HERE / 'clean'}")


def errors():
    import json
    doc = json.loads((HERE / "dirty" / "_sidecar.json").read_text())
    for item in doc["distribution"]:
        if item.get("name") == "omop/person.csv":
            item["md5"] = "0" * 32
    (HERE / "dirty" / "_sidecar.errors.json").write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    errors() if sys.argv[1] == "--errors" else main(sys.argv[1])
