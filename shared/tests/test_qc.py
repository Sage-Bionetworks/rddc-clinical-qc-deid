import csv
import json

from rddc_screen_common.qc import QCError, check_file, report


def test_failure_reports_only_code_and_location(tmp_path):
    def invalid(path):
        raise QCError("invalid_record", 3)
    out = tmp_path / "qc.json"
    result = check_file(invalid, "sensitive-source-path", "urn:uuid:test", out)
    assert result["status"] == "fail"
    assert result["error"] == "invalid_record" and result["record"] == 3
    assert "sensitive-source-path" not in out.read_text()


def test_report_fails_if_any_file_fails(tmp_path):
    paths = []
    for index, status in enumerate(("pass", "fail")):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps(dict(file=str(index), status=status, records=0, error="", record=0)))
        paths.append(path)
    out = tmp_path / "qc.tsv"
    assert not report(paths, out)
    assert len(list(csv.DictReader(out.open(), delimiter="\t"))) == 2
    assert report(paths[:1], out)
    assert not report([], out)
