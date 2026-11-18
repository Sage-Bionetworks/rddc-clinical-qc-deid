"""Check a screen_fhir or screen_omop run's outputs: python3 -I tests/check_results.py RESULTS_DIR quarantine|pass

quarantine: at least one file has direct_identifiers, and findings.tsv has stop rows.
pass: no file has direct_identifiers. Either way, every screened file has a result, and
results.json is the list the dispatcher records ([{file, properties}]).
"""

import csv
import json
import sys
from pathlib import Path

out, want = Path(sys.argv[1]), sys.argv[2]
qc = list(csv.DictReader(open(out / "qc" / "qc.tsv"), delimiter="\t"))
assert qc and all(r["status"] == "pass" for r in qc), "screen ran without passing structural QC"
results = json.loads((out / "results.json").read_text())
intake = list(csv.DictReader(open(out / "intake" / "intake.tsv"), delimiter="\t"))
screened = {r["file_id"] for r in intake if r["route"] == "screened"}
assert {r["file"].removeprefix("urn:uuid:") for r in qc} == screened, "QC and screening file sets differ"
assert screened and {r["file"].removeprefix("urn:uuid:") for r in results} == screened, "a screened file has no result"
assert all(set(r) == {"file", "properties"} for r in results), "results.json items are {file, properties}"
held = [r["file"] for r in results if "direct_identifiers" in r["properties"]]
stops = [r for r in csv.DictReader(open(out / "findings.tsv"), delimiter="\t") if r["action"] == "stop"]
if want == "quarantine":
    assert held and stops, "expected direct identifiers"
else:
    assert not held and not stops, f"unexpected direct identifiers: {held}"
print(f"{out}: {len(results)} file(s), {len(held)} with direct identifiers ({want}, as expected)")
