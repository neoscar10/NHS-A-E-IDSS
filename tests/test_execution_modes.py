import hashlib
import json
from pathlib import Path

import pytest

from src.utils.execution_modes import NotebookSession, STAGES, _state
from src.utils.evidence_exporter import MILESTONES


@pytest.fixture
def project(tmp_path):
    for rel in ('src/data', 'tests', 'notebooks', 'data/raw'):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / 'src/data/data_ingestion.py').write_text('# fixture')
    (tmp_path / 'data/raw/a.csv').write_text('original')
    return tmp_path


def record(repo, milestone, run='20260101T000000Z_abcd', status='COMPLETE'):
    folder = repo / 'docs/evidence' / MILESTONES[milestone] / run
    folder.mkdir(parents=True)
    payload = b'count\n1\n'
    (folder / 'report.csv').write_bytes(payload)
    (folder / 'evidence_manifest.json').write_text(json.dumps({
        'milestone': milestone, 'run_id': run, 'status': status, 'test_runs': [],
        'artifacts': {'report.csv': {'sha256': hashlib.sha256(payload).hexdigest()}}
    }))
    return folder


def test_explore_is_read_only(project):
    for m in STAGES[1]:
        record(project, m)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    s = NotebookSession(project, 'explore', 1)
    assert s.artifact('M01', 'report.csv').exists()
    s.finish()
    assert before == {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()}


def test_incomplete_explore_rejected(project):
    record(project, 'M03', status='IN_PROGRESS')
    with pytest.raises(ValueError, match='not complete'):
        NotebookSession(project, 'explore', 2)


def test_artifact_integrity(project):
    p = record(project, 'M03')
    s = NotebookSession(project, 'explore', 2)
    (p / 'report.csv').write_bytes(b'count\r\n1\r\n')
    assert s.artifact('M03', 'report.csv').exists()
    (p / 'report.csv').write_bytes(b'count\n2\n')
    with pytest.raises(ValueError, match='fingerprint'):
        s.artifact('M03', 'report.csv')


def test_rebuild_separate_and_ordered(project):
    s = NotebookSession(project, 'rebuild', 1)
    assert s.repo != project and (s.repo / 'data/raw/a.csv').read_text() == 'original'
    for m in STAGES[1]:
        record(s.repo, m)
    s.finish()
    assert _state(s.repo)['completed'] == 1
    assert not (project / 'docs').exists()
    e = NotebookSession(project, 'explore', 1, view_rebuild=True)
    assert e.repo == s.repo
    with pytest.raises(ValueError, match='in order'):
        NotebookSession(project, 'rebuild', 3)
    t = NotebookSession(project, 'rebuild', 2)
    record(t.repo, 'M03')
    t.finish()
    assert _state(t.repo)['completed'] == 2
    with pytest.raises(ValueError, match='in order'):
        NotebookSession(project, 'rebuild', 2)


def test_rebuild_reset_requires_explicit_choice(project):
    s = NotebookSession(project, 'rebuild', 1)
    with pytest.raises(FileExistsError):
        NotebookSession(project, 'rebuild', 1)
    t = NotebookSession(project, 'rebuild', 1, reset_rebuild=True)
    assert s.repo == t.repo
    assert (project / 'data/raw/a.csv').read_text() == 'original'


def test_unknown_workspace_not_removed(project):
    work = project / '.work/rebuild'
    work.mkdir(parents=True)
    (work / 'important.txt').write_text('keep')
    with pytest.raises(ValueError, match='not an owned workspace'):
        NotebookSession(project, 'rebuild', 1, reset_rebuild=True)
    assert (work / 'important.txt').read_text() == 'keep'


def test_snapshot_requires_new_complete_run(project):
    old = record(project, 'M03')
    s = NotebookSession(project, 'snapshot', 2)
    with pytest.raises(RuntimeError, match='exactly one'):
        s.finish()
    record(project, 'M03', run='20260102T000000Z_ffff')
    s.finish()
    assert old.is_dir()


def test_failed_rebuild_not_completed(project):
    s = NotebookSession(project, 'rebuild', 1)
    record(s.repo, 'M01')
    record(s.repo, 'M02', status='COMPLETE_REVIEW_REQUIRED')
    with pytest.raises(ValueError, match='not complete'):
        s.finish()
    assert _state(s.repo)['completed'] == 0
