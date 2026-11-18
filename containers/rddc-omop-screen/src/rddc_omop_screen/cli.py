"""rddc-omop-screen: screen OMOP CDM tables for identifiers, and merge per-file results.

  rddc-omop-screen file FILE --file-id URN --name NAME --table CDM_TABLE
                        [--encoding-format MEDIA_TYPE] [--provider-policy stop|review]
                        [--research-id-pattern REGEX] [--allow-list TSV] [--rules RULES]
                        --findings OUT.tsv --result OUT.json
  rddc-omop-screen report RESULT.json... --findings FINDINGS.tsv... --out-dir DIR

`file` writes the findings of one table (TSV, no values) and its result: the data
properties the screen reports for it. `report` merges the results into results.json,
the list the dispatcher records on the screen step ([{file, properties}]), and writes
findings.tsv and summary.tsv. Exit status is 0 whatever is found: a finding is a result,
not a failure.
"""

import argparse
import csv
import json
import sys

from . import __version__
from .qc import validate
from rddc_screen_common.qc import check_file
from .screen import CHECKED, Screen, load_allow_list, load_rules, properties

FINDING_FIELDS = ["file_id", "file", "table", "column", "rule", "detector", "action", "count", "first_row"]


def cmd_qc(a):
    check_file(validate, a.path, a.file_id, a.result, table=a.table, encoding_format=a.encoding_format)


def cmd_file(a):
    rules = load_rules(a.rules)
    allow = load_allow_list(a.allow_list) if a.allow_list else None
    screen = Screen(rules, a.provider_policy, a.research_id_pattern or None, allow)
    records, found, first = screen.file(a.path, a.table, a.encoding_format)
    with open(a.findings, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        for k in sorted(found, key=lambda k: (k.action != "stop", k.column, k.rule, k.detector)):
            w.writerow([a.file_id, a.name, k.table, k.column, k.rule, k.detector, k.action, found[k], first[k]])
    result = {"file": a.file_id, "name": a.name, "table": a.table.lower(), "records": records,
              "properties": properties(found), "checked": CHECKED, "rulesVersion": rules.get("version"),
              "screenVersion": __version__, "providerPolicy": a.provider_policy,
              "researchIdChecked": bool(a.research_id_pattern), "allowListChecked": allow is not None}
    with open(a.result, "w") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")


def cmd_report(a):
    results = sorted((json.load(open(p)) for p in a.results), key=lambda r: r["name"])
    with open(f"{a.out_dir}/results.json", "w") as fh:
        json.dump([{"file": r["file"], "properties": r["properties"]} for r in results], fh, indent=2)
        fh.write("\n")
    with open(f"{a.out_dir}/summary.tsv", "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["file_id", "file", "table", "records", "verdict"] + CHECKED)
        for r in results:
            verdict = "quarantine" if "direct_identifiers" in r["properties"] else "pass"
            w.writerow([r["file"], r["name"], r.get("table", ""), r["records"], verdict]
                       + [str(p in r["properties"]).lower() for p in CHECKED])
    rows = []
    for p in a.findings:
        with open(p) as fh:
            rows += list(csv.reader(fh, delimiter="\t"))
    with open(f"{a.out_dir}/findings.tsv", "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(FINDING_FIELDS)
        w.writerows(sorted(rows, key=lambda r: (r[6] != "stop", r[1], r[3], r[4], r[5])))
    held = [r["name"] for r in results if "direct_identifiers" in r["properties"]]
    print(f"{len(results)} table(s) screened; {len(held)} with direct identifiers"
          + (f": {', '.join(held)}" if held else ""), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rddc-omop-screen", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("qc", help="check file structure before screening")
    q.add_argument("path")
    q.add_argument("--file-id", required=True)
    q.add_argument("--result", required=True)
    q.add_argument("--table", required=True)
    q.add_argument("--encoding-format")
    q.set_defaults(fn=cmd_qc)
    f = sub.add_parser("file", help="screen one OMOP table")
    f.add_argument("path")
    f.add_argument("--file-id", required=True, help="the file's @id in the sidecar (urn:uuid:...)")
    f.add_argument("--name", required=True, help="the file's name in the sidecar")
    f.add_argument("--table", required=True, help="the file's cdmTable in the sidecar")
    f.add_argument("--encoding-format", help="the file's encodingFormat (default: from the file name)")
    f.add_argument("--provider-policy", choices=["stop", "review"], default="stop",
                   help="clinician and site identity: a direct identifier (stop) or a finding for review")
    f.add_argument("--research-id-pattern", help="regex every person_source_value must match")
    f.add_argument("--allow-list", help="TSV (table, column, value) of the source's reviewed values")
    f.add_argument("--rules", help="rules YAML (default: the packaged rules)")
    f.add_argument("--findings", required=True)
    f.add_argument("--result", required=True)
    f.set_defaults(fn=cmd_file)
    r = sub.add_parser("report", help="merge per-file results")
    r.add_argument("results", nargs="+")
    r.add_argument("--findings", nargs="+", default=[])
    r.add_argument("--out-dir", required=True)
    r.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
