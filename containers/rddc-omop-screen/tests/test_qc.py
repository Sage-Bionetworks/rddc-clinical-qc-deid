import gzip
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from rddc_omop_screen.cli import main
from rddc_omop_screen.qc import validate
from rddc_screen_common.qc import QCError


@pytest.mark.parametrize("text,code", [
    ("", "empty_header"),
    ("person_id,\n1,2\n", "empty_header"),
    ("person_id,PERSON_ID\n1,2\n", "duplicate_column"),
    ("person_id\n1\n", "missing_required_column"),
])
def test_invalid_person_headers(tmp_path, text, code):
    path = tmp_path / "person.csv"
    path.write_text(text)
    with pytest.raises(QCError, match=code):
        validate(path, "person")


def test_short_and_long_rows_fail_without_values(tmp_path):
    for row in ("1", "1,synthetic-secret,extra"):
        path = tmp_path / "location.csv"
        path.write_text("location_id,address_1\n" + row + "\n")
        out = tmp_path / "qc.json"
        main(["qc", str(path), "--table", "location", "--file-id", "urn:uuid:test", "--result", str(out)])
        report = json.loads(out.read_text())
        assert report["error"] == "row_width_mismatch" and report["record"] == 1
        assert "synthetic-secret" not in out.read_text()


def test_csv_tsv_gzip_and_parquet(tmp_path):
    for suffix,delimiter in (("csv", ","), ("tsv", "\t")):
        path = tmp_path / f"location.{suffix}.gz"
        with gzip.open(path, "wt") as fh:
            fh.write(f"location_id{delimiter}city\n1{delimiter}Town\n")
        assert validate(path, "location") == 1
    path = tmp_path / "location.parquet"
    pq.write_table(pa.table({"location_id": [1], "city": ["Town"]}), path)
    assert validate(path, "location") == 1
    pq.write_table(pa.table({"city": ["Town"]}), path)
    with pytest.raises(QCError, match="missing_required_column"):
        validate(path, "location")


def test_corrupt_files_fail_safely(tmp_path):
    for name,contents in (("location.csv", b'location_id,city\n1,"unterminated'),
                          ("location.parquet", b"not a parquet file"),
                          ("location.csv.gz", gzip.compress(b"location_id\n1\n")[:-8])):
        path = tmp_path / name
        path.write_bytes(contents)
        out = tmp_path / "qc.json"
        main(["qc", str(path), "--table", "location", "--file-id", "urn:uuid:test", "--result", str(out)])
        assert json.loads(out.read_text())["status"] == "fail"


def test_committed_batches_pass_qc():
    import os
    fixtures = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_omop"))
    assert fixtures.exists(), "fixture batches must be available"
    for batch in ("clean", "dirty"):
        sidecar = json.loads((fixtures / batch / "_sidecar.json").read_text())
        tables = [entry for entry in sidecar["distribution"] if entry.get("cdmTable")]
        assert tables
        for entry in tables:
            assert validate(fixtures / batch / entry["contentUrl"], entry["cdmTable"]) >= 0


def test_parquet_column_normalization_matches_screening(tmp_path):
    from rddc_omop_screen.screen import Screen, load_rules, properties
    path = tmp_path / "location.parquet"
    pq.write_table(pa.table({" LOCATION_ID ": [1], " ADDRESS_1 ": ["synthetic address"]}), path)
    assert validate(path, "location") == 1
    _, findings, _ = Screen(load_rules()).file(str(path), "location")
    assert "direct_identifiers" in properties(findings)
