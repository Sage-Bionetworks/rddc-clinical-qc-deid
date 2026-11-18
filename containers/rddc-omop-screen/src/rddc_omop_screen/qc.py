"""Check table structure and required columns before identifier screening."""

import csv
import gzip
import json
import zlib
from importlib import resources

from rddc_screen_common.qc import QCError
from .screen import PARQUET, file_format


def header(names, table):
    names = [name.strip().lower() for name in names]
    if not names or any(not name for name in names):
        raise QCError("empty_header")
    if len(names) != len(set(names)):
        raise QCError("duplicate_column")
    required = json.loads(resources.files(__package__).joinpath("qc_columns.json").read_text())
    if not set(required.get(table.lower(), ())) <= set(names):
        raise QCError("missing_required_column")
    return names


def validate(path, table, encoding_format=None):
    fmt = file_format(str(path), encoding_format)
    if fmt == PARQUET:
        import pyarrow as pa
        import pyarrow.parquet as pq
        try:
            parquet = pq.ParquetFile(path)
            header(parquet.schema_arrow.names, table)
            return sum(batch.num_rows for batch in parquet.iter_batches(batch_size=10_000))
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            raise QCError("invalid_parquet") from None
    opener = gzip.open if str(path).endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t" if fmt == "text/tab-separated-values" else ",", strict=True)
            names = header(next(reader, []), table)
            records = 0
            for records, row in enumerate(reader, 1):
                if len(row) != len(names):
                    raise QCError("row_width_mismatch", records)
            return records
    except csv.Error:
        raise QCError("invalid_delimited_file") from None
    except zlib.error:
        raise QCError("unreadable_file") from None
