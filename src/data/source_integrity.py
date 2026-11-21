"""Verify the fixed source register and independently compare staged source values."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

REGISTER = 'docs/source_baseline.json'
PROVENANCE = ['source_month', 'source_file', 'source_sha256', 'source_record_number']


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f'blob {len(data)}\0'.encode('ascii') + data).hexdigest()


def verify_source_register(repo):
    repo = Path(repo).resolve()
    register = repo / REGISTER
    if register.resolve() != register or not register.is_file():
        raise FileNotFoundError('Fixed source register is missing or redirected')
    baseline = json.loads(register.read_text(encoding='utf-8'))
    entries = baseline['files']
    paths = [e['path'] for e in entries]
    if not entries or len(set(paths)) != len(paths):
        raise ValueError('Invalid source register: empty or duplicate paths')
    root = repo / 'data/raw'
    if not root.is_dir() or root.resolve() != root:
        raise ValueError('Invalid raw source directory')
    actual = sorted(p.relative_to(repo).as_posix() for p in root.rglob('*')
                    if p.is_file() and p.suffix.lower() == '.csv')
    if sorted(paths) != actual:
        raise ValueError('Source collection differs from the fixed register')
    for e in entries:
        p = repo / e['path']
        if p.resolve() != p or not re.fullmatch(r'[0-9a-f]{40}', e['git_blob_sha1']):
            raise ValueError(f'Invalid source register entry: {e["path"]}')
        raw = p.read_bytes()
        lf = raw.replace(b'\r\n', b'\n')
        variants = (raw, lf, lf.replace(b'\n', b'\r\n'))
        if e['git_blob_sha1'] not in {git_blob_sha(v) for v in variants}:
            raise ValueError(f'Source differs from fixed register: {e["path"]}')
    canonical = json.dumps(baseline, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'source_version': baseline['source_version'],
            'source_baseline_sha256': hashlib.sha256(canonical).hexdigest(),
            'source_files_verified': len(entries)}


def verify_source_to_staging(repo, staged, *, other_path=None):
    """Compare every original field and provenance key to independently parsed CSV records."""
    if __package__:
        from .data_ingestion import EXPECTED_COLUMNS, filename_month
    else:
        from data_ingestion import EXPECTED_COLUMNS, filename_month
    repo = Path(repo).resolve()
    identity = verify_source_register(repo)
    baseline = json.loads((repo / REGISTER).read_text(encoding='utf-8'))
    cols = EXPECTED_COLUMNS + PROVENANCE
    records = []
    for entry in baseline['files']:
        rel = entry['path']
        path = repo / rel
        month = filename_month(path)
        if month is None:
            raise ValueError(f'Cannot identify source reporting month: {rel}')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, strict=True)
            header = next(reader)
            if header[:len(EXPECTED_COLUMNS)] != EXPECTED_COLUMNS:
                raise ValueError(f'Unexpected source header: {rel}')
            for ordinal, row in enumerate(reader, 1):
                if len(row) != len(header) or any(v.strip() for v in row[len(EXPECTED_COLUMNS):]):
                    raise ValueError(f'Invalid source row shape: {rel}:{ordinal}')
                records.append(row[:len(EXPECTED_COLUMNS)] + [month, rel, sha, str(ordinal)])
    expected = pd.DataFrame(records, columns=cols, dtype='string')
    keys = ['source_file', 'source_record_number']

    def compare(frame, label):
        if list(frame.columns) != cols or len(frame) != len(expected):
            raise ValueError(f'Source-to-staging schema or row count mismatch: {label}')
        # Preserve source text; do not coerce missing numeric values to zero.
        actual = frame.astype('string').fillna('').sort_values(keys).reset_index(drop=True)
        ref = expected.sort_values(keys).reset_index(drop=True)
        if actual.duplicated(keys).any() or not actual.equals(ref):
            raise ValueError(f'Source-to-staging field mismatch: {label}')

    compare(staged, 'selected staging data')
    if other_path is not None and Path(other_path).is_file():
        other_path = Path(other_path)
        if other_path.suffix == '.parquet':
            alternate = pd.read_parquet(other_path)
        else:
            alternate = pd.read_csv(other_path, dtype=str, keep_default_na=False, na_filter=False,
                                    encoding='utf-8-sig', low_memory=False)
        compare(alternate, other_path.name)
    if verify_source_register(repo) != identity:
        raise ValueError('Source register changed during verification')
    return {**identity, 'source_rows_verified': len(expected), 'source_to_staging_check': 'MATCH'}
