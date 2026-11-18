"""Screen OMOP CDM 5.4 tables for identifiers.

Reads one table (CSV or TSV, optionally gzipped, or Parquet) and reports findings by
column and rule. Findings never include the values found: only the table, the column,
the rule or detector, how many values matched, and the first row.
"""

import csv
import gzip
import re
from collections import Counter
from dataclasses import dataclass
from importlib import resources as pkg

import yaml

from rddc_screen_common import detectors

PROPERTY = {"stop": "direct_identifiers", "dates": "dates", "zip_codes": "zip_codes", "free_text": "free_text"}
# The properties this screen is authoritative for. The orchestrator replaces a file's
# predicted values of these with the screen's report.
CHECKED = sorted(PROPERTY.values())
PARQUET = "application/vnd.apache.parquet"


def load_rules(path=None):
    text = open(path).read() if path else pkg.files(__package__).joinpath("rules.yaml").read_text()
    return yaml.safe_load(text)


def load_allow_list(path):
    """{(table, column): {values}} from a TSV with the header table, column, value."""
    allowed = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            allowed.setdefault((r["table"].lower(), r["column"].lower()), set()).add(r["value"])
    return allowed


@dataclass(frozen=True)
class Key:
    table: str
    column: str
    rule: str
    detector: str
    action: str


def file_format(path, encoding_format=None):
    if encoding_format in (PARQUET, "text/csv", "text/tab-separated-values"):
        return encoding_format
    name = path.lower().removesuffix(".gz")
    if name.endswith(".parquet"):
        return PARQUET
    return "text/tab-separated-values" if name.endswith((".tsv", ".tab")) else "text/csv"


def rows_in(path, fmt):
    """Rows as dicts with lower-case column names; empty strings are None."""
    if fmt == PARQUET:
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches(batch_size=10_000):
            names = [n.strip().lower() for n in batch.schema.names]
            for row in batch.to_pylist():
                yield dict(zip(names, row.values()))
        return
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t" if fmt == "text/tab-separated-values" else ",")
        header = [h.strip().lower() for h in next(reader, [])]
        for row in reader:
            yield {h: (v if v != "" else None) for h, v in zip(header, row)}


class Screen:
    def __init__(self, rules, provider_policy="stop", research_id_pattern=None, allow_list=None):
        if provider_policy not in ("stop", "review"):
            raise ValueError("provider_policy must be stop or review")
        self.rules = rules
        self.provider_policy = provider_policy
        self.research_id = re.compile(research_id_pattern) if research_id_pattern else None
        self.allow_list = allow_list
        self.url_hosts = tuple(rules.get("patterns", {}).get("url_hosts", []))
        udi = rules.get("udi", {})
        self.udi = (udi.get("table"), udi.get("column"), re.compile(udi["allowed"])) if udi else None

    def action(self, a):
        return self.provider_policy if a == "provider" else a

    def plan(self, table, column):
        """What to do with every non-empty value of a column: [(rule, detector, action)] to
        add as they are, and whether to date-check, allow-list check and pattern-screen it."""
        r = self.rules
        cols = r.get("columns", {}).get(table, {})
        fixed = [(f"column:{a}", "", a) for a, names in cols.items() if a != "dates" and column in names]
        is_date = column.endswith(tuple(r.get("dates", {}).get("suffixes", []))) or column in cols.get("dates", [])
        al = r.get("allow_list", {})
        sk = r.get("source_key", {})
        own_rule = fixed or (table, column) == (sk.get("table"), sk.get("column"))  # checked on its own
        listed = (self.allow_list is not None and not own_rule and
                  (column.endswith(tuple(al.get("suffixes", []))) or f"{table}.{column}" in al.get("also", [])))
        free = column in cols.get("free_text", [])
        return fixed, is_date, listed, not free and not is_date

    def file(self, path, table, encoding_format=None):
        table = table.lower()
        r = self.rules
        found, first = Counter(), {}

        def add(column, rule, detector, action, n):
            k = Key(table, column, rule, detector, self.action(action))
            found[k] += 1
            first.setdefault(k, n)

        if table not in r.get("cdm_tables", []):
            add("", "unknown_table", "", "review", 0)
        skip = table in r.get("skip_tables", [])
        plans = {}
        sk = r.get("source_key", {})
        links = r.get("person_links", {})
        long_len = r.get("long_string", {}).get("length")
        long_action = r.get("long_string", {}).get("action", "free_text")
        date_action = r.get("dates", {}).get("action", "dates")
        pattern_action = r.get("patterns", {}).get("action", "stop")
        allow_action = r.get("allow_list", {}).get("action", "review")
        records = 0
        for n, row in enumerate(rows_in(path, file_format(path, encoding_format)), 1):
            records += 1
            if skip:
                continue
            for column, value in row.items():
                if value is None or value == "":
                    continue
                if column not in plans:
                    plans[column] = self.plan(table, column)
                fixed, is_date, listed, screened = plans[column]
                for rule, det, action in fixed:
                    add(column, rule, det, action, n)
                text = value if isinstance(value, str) else str(value)
                if is_date:
                    add(column, "dates", "", date_action, n)
                if self.udi and (table, column) == self.udi[:2] and not self.udi[2].match(text.strip()):
                    add(column, "udi", "", "stop", n)
                if (table, column) == (sk.get("table"), sk.get("column")):
                    if self.research_id is None:
                        add(column, "source_key", "unchecked", "review", n)
                    elif not self.research_id.fullmatch(text):
                        add(column, "source_key", "not_research_id", "stop", n)
                if listed and text not in self.allow_list.get((table, column), ()):
                    add(column, "allow_list", "", allow_action, n)
                if screened and isinstance(value, str):
                    for d in detectors.scan(value, self.url_hosts):
                        add(column, "pattern", d, pattern_action, n)
                    if long_len and len(value) > long_len:
                        add(column, "long_string", "", long_action, n)
            if table == links.get("table"):
                if all(str(row.get(c)) == links.get("person_domain") for c in links.get("domain_columns", [])):
                    add("", "person_link", "", "review", n)
        return records, found, first


def properties(found):
    return sorted({PROPERTY[k.action] for k in found if k.action in PROPERTY})
