"""Verify that one invalid file blocks screening of the entire batch."""

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

standard, profile = sys.argv[1:]
root = Path(__file__).resolve().parents[1]
case = json.loads((root / "tests" / f"screen_{standard}" / "qc_case.json").read_text())
(root / "results").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix=f"{standard}-qc-", dir=root / "results") as directory:
    batch = Path(directory)
    entries = []
    for label in ("valid", "invalid"):
        name = f"{label}{case['suffix']}"
        data = case[label].encode()
        (batch / name).write_bytes(data)
        entry = {"@type": "cr:FileObject", "@id": f"urn:uuid:qc-{label}", "name": name,
                 "contentUrl": name, "additionalType": case["additionalType"],
                 "md5": hashlib.md5(data).hexdigest()}
        if "cdmTable" in case:
            entry["cdmTable"] = case["cdmTable"]
        entries.append(entry)
    sidecar = batch / "_sidecar.json"
    sidecar.write_text(json.dumps({"@id": "urn:uuid:qc-batch", "distribution": entries}))
    out = batch / "out"
    trace = batch / "trace.tsv"
    command = [str(root / ".tools" / "nextflow"), "run", ".", "-main-script",
               f"workflows/screen_{standard}/main.nf", "-profile", profile,
               "-with-trace", str(trace), "--sidecar", str(sidecar), "--outdir", str(out)]
    env = dict(os.environ, PATH=str(root / ".venv" / "bin") + os.pathsep + os.environ["PATH"])
    run = subprocess.run(command, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert run.returncode != 0 and "Structural QC failed" in run.stdout, run.stdout
    rows = list(csv.DictReader((out / "qc" / "qc.tsv").open(), delimiter="\t"))
    assert {r["status"] for r in rows} == {"pass", "fail"}, rows
    assert not (out / "results.json").exists(), "QC failure produced screening results"
    tasks = list(csv.DictReader(trace.open(), delimiter="\t"))
    assert not any("SCREEN_" in task["name"] for task in tasks), tasks
    print(f"screen_{standard}: one QC failure blocks screening of the whole batch")
