import gzip
import json
from pathlib import Path

import pytest

from rddc_fhir_screen.cli import main
from rddc_fhir_screen.qc import validate
from rddc_screen_common.qc import QCError


@pytest.mark.parametrize("text,code", [
    ("", "empty_file"),
    ('{"resourceType":', "invalid_json"),
    ('[]', "resource_not_object"),
    ('{"id":"p1"}', "invalid_resource_type"),
    ('{"resourceType":123}', "invalid_resource_type"),
    ('{"resourceType":"Patient","contained":{}}', "contained_not_array"),
    ('{"resourceType":"Bundle","entry":{}}', "bundle_entry_not_array"),
    ('{"resourceType":"Bundle","entry":[{}]}', "bundle_entry_resource_required"),
    ('{"resourceType":"Patient","x":NaN}', "invalid_json"),
])
def test_invalid_structure(tmp_path, text, code):
    path = tmp_path / "input.json"
    path.write_text(text)
    with pytest.raises(QCError, match=code):
        validate(path)


def test_bundle_and_gzipped_ndjson(tmp_path):
    patient = {"resourceType": "Patient", "id": "p1"}
    path = tmp_path / "input.ndjson.gz"
    with gzip.open(path, "wt") as fh:
        fh.write(json.dumps(patient) + "\n" + json.dumps(patient) + "\n")
    assert validate(path) == 2
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"resourceType": "Bundle", "entry": [{"resource": patient}]}))
    assert validate(bundle) == 1


def test_invalid_line_reports_location_without_value(tmp_path):
    path = tmp_path / "input.ndjson"
    path.write_text('{"resourceType":"Patient"}\n{"name":"synthetic-secret"}\n')
    result = tmp_path / "result.json"
    main(["qc", str(path), "--file-id", "urn:uuid:test", "--result", str(result)])
    report = json.loads(result.read_text())
    assert report["status"] == "fail" and report["record"] == 2
    assert "synthetic-secret" not in result.read_text()


def test_truncated_gzip_reports_failure(tmp_path):
    path = tmp_path / "input.ndjson.gz"
    path.write_bytes(gzip.compress(b'{"resourceType":"Patient"}')[:-8])
    result = tmp_path / "result.json"
    main(["qc", str(path), "--file-id", "urn:uuid:test", "--result", str(result)])
    assert json.loads(result.read_text())["error"] == "unreadable_file"


def test_committed_batches_pass_qc():
    import os
    fixtures = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_fhir"))
    assert fixtures.exists(), "fixture batches must be available"
    files = list(fixtures.glob("*/fhir/*.ndjson.gz"))
    assert files
    for path in files:
        assert validate(path) > 0
