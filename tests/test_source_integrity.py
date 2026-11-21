import json

import pandas as pd
import pytest

from src.data.data_ingestion import run_pipeline
from src.data.source_integrity import REGISTER, git_blob_sha, verify_source_register, verify_source_to_staging
from src.data.data_validation import validate_dataset
from test_data_ingestion import _fixture, _pin_sources


def test_missing_register_blocks_ingestion(tmp_path):
    repo = _fixture(tmp_path)
    (repo / REGISTER).unlink()
    with pytest.raises(FileNotFoundError, match='register'):
        run_pipeline(repo, start='2022-01', end='2022-02')


def test_changed_raw_blocks_fresh_ingestion(tmp_path):
    repo = _fixture(tmp_path)
    p = next((repo / 'data/raw').rglob('*.csv'))
    p.write_bytes(p.read_bytes().replace(b'100', b'999') if b'100' in p.read_bytes() else p.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='fixed register'):
        run_pipeline(repo, start='2022-01', end='2022-02')


def test_extra_source_rejected(tmp_path):
    repo = _fixture(tmp_path)
    (repo / 'data/raw/2022/extra.csv').write_text('extra')
    with pytest.raises(ValueError, match='collection differs'):
        verify_source_register(repo)


def test_original_values_verified(tmp_path):
    repo = _fixture(tmp_path)
    result = run_pipeline(repo, start='2022-01', end='2022-02')
    identity = verify_source_to_staging(repo, result['combined'])
    assert identity['source_rows_verified'] == 4
    assert validate_dataset(repo)['summary']['source_integrity']['source_to_staging_check'] == 'MATCH'


def test_matching_corrupted_counts_still_rejected(tmp_path):
    repo = _fixture(tmp_path)
    result = run_pipeline(repo, start='2022-01', end='2022-02')
    altered = result['combined'].copy()
    altered.loc[:1, 'A&E attendances Type 1'] = '999'
    with pytest.raises(ValueError, match='field mismatch'):
        verify_source_to_staging(repo, altered)
    altered.to_csv(repo / 'data/staging/ae_historical_raw_combined.csv', index=False)
    with pytest.raises(ValueError, match='field mismatch'):
        validate_dataset(repo)


def test_provenance_changes_rejected(tmp_path):
    repo = _fixture(tmp_path)
    frame = run_pipeline(repo, start='2022-01', end='2022-02')['combined'].copy()
    frame.loc[0, 'source_record_number'] = 2
    with pytest.raises(ValueError, match='field mismatch'):
        verify_source_to_staging(repo, frame)


def test_git_line_endings_accepted(tmp_path):
    repo = _fixture(tmp_path)
    before = verify_source_register(repo)
    p = next((repo / 'data/raw').rglob('*.csv'))
    p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
    assert verify_source_register(repo) == before


def test_conflicting_alternate_csv_rejected(tmp_path):
    repo = _fixture(tmp_path)
    frame = run_pipeline(repo, start='2022-01', end='2022-02')['combined']
    alternate = tmp_path / 'alternate.csv'
    changed = frame.copy()
    changed.loc[0, 'Org name'] = 'Wrong name'
    changed.to_csv(alternate, index=False)
    with pytest.raises(ValueError, match='field mismatch'):
        verify_source_to_staging(repo, frame, other_path=alternate)
