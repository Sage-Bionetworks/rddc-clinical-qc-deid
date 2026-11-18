"""Structural QC reports contain locations and fixed error codes, never source values."""

import argparse
import csv
import json
from pathlib import Path


class QCError(ValueError):
    def __init__(self, code, record=0):
        self.code = code
        self.record = record
        super().__init__(code)


def check_file(check, path, file_id, output, **kwargs):
    result = {"file": file_id, "status": "pass", "records": 0, "error": "", "record": 0}
    try:
        result["records"] = check(path, **kwargs)
    except QCError as exc:
        result.update(status="fail", error=exc.code, record=exc.record)
    except (OSError, EOFError, UnicodeError):
        result.update(status="fail", error="unreadable_file")
    Path(output).write_text(json.dumps(result, indent=2) + "\n")
    return result


def report(paths, output):
    results = sorted((json.loads(Path(p).read_text()) for p in paths), key=lambda r: r["file"])
    with open(output, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file", "status", "records", "error", "record"], delimiter="\t")
        writer.writeheader()
        writer.writerows(results)
    return bool(results) and all(r["status"] == "pass" for r in results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    # A failed check is a report. The Nextflow workflow enforces the batch gate.
    print("pass" if report(args.results, args.output) else "fail")
