"""Synthetic tests for research evidence preservation."""
import json
from pathlib import Path
import pytest
from src.utils.evidence_exporter import EvidenceRun, digest, find_repo, snapshot_existing

@pytest.fixture
def repo(tmp_path):
    for rel, value in {'src/data/data_ingestion.py':'# fixture', 'src/utils/evidence_exporter.py':'# fixture',
                       'data/raw/a.csv':'source', 'docs/source_manifest.csv':'a,b\n1,2\n',
                       'docs/m01_coverage.json':'{"source_files":1}', 'tests/test_dummy.py':'def test_ok(): assert True\n'}.items():
        p=tmp_path/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value, encoding='utf-8')
    return tmp_path

def test_find_repo(repo):
    assert find_repo(repo/'data/raw') == repo

def test_unique_runs_and_prior_preserved(repo):
    a=EvidenceRun(repo,'M01','test'); a.write_text('reports/a.txt','old'); a.finish()
    b=EvidenceRun(repo,'M01','test'); b.write_text('reports/a.txt','new'); b.finish()
    assert a.path != b.path and (a.path/'reports/a.txt').read_text()=='old'

def test_exact_copy_and_hash(repo):
    run=EvidenceRun(repo,'M01','test'); target=run.copy_report('docs/source_manifest.csv'); run.finish()
    m=json.loads((run.path/'evidence_manifest.json').read_text())
    assert target.read_bytes()==(repo/'docs/source_manifest.csv').read_bytes()
    assert m['artifacts']['reports/source_manifest.csv']['sha256']==digest(target)
    assert m['status']=='COMPLETE'

def test_reject_escape_and_overwrite(repo):
    run=EvidenceRun(repo,'M01','test')
    with pytest.raises(ValueError): run.write_text('../../escape.txt','bad')
    run.write_text('reports/a.txt','original')
    with pytest.raises(FileExistsError): run.write_text('reports/a.txt','changed')
    with pytest.raises(ValueError): run.write_text('evidence_manifest.json','bad')
    run.finish()
    with pytest.raises(RuntimeError): run.write_text('reports/b.txt','bad')

def test_input_change_marks_review(repo):
    run=EvidenceRun(repo,'M02','test'); run.record_input('data/raw/a.csv')
    (repo/'data/raw/a.csv').write_text('changed'); run.finish()
    assert json.loads((run.path/'evidence_manifest.json').read_text())['status']=='COMPLETE_REVIEW_REQUIRED'

def test_interrupted_run_is_not_complete(repo):
    run=EvidenceRun(repo,'M03','test')
    assert json.loads((run.path/'evidence_manifest.json').read_text())['status']=='IN_PROGRESS'

def test_missing_and_optional_input(repo):
    run=EvidenceRun(repo,'M01','test'); run.record_input('no_file',required=False)
    with pytest.raises(FileNotFoundError): run.record_input('other_file')
    run.finish(); assert json.loads((run.path/'evidence_manifest.json').read_text())['inputs']['no_file']['status']=='NOT_PRESENT'

def test_failed_test_log_is_review(repo, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],1,'failure',''))
    run=EvidenceRun(repo,'M01','test'); assert run.run_tests('tests/test_dummy.py') == 1; run.finish()
    assert 'Exit code: 1' in (run.path/'test_results/pytest_01.txt').read_text()
    assert json.loads((run.path/'evidence_manifest.json').read_text())['status']=='COMPLETE_REVIEW_REQUIRED'

def test_archive_existing_no_mutation(repo):
    before=(repo/'docs/source_manifest.csv').read_bytes(); p=snapshot_existing(repo,'M01')
    assert (p/'reports/source_manifest.csv').read_bytes()==before==(repo/'docs/source_manifest.csv').read_bytes()

def test_save_png(repo):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig=Figure(figsize=(1,1)); FigureCanvasAgg(fig); fig.subplots().plot([1,2])
    run=EvidenceRun(repo,'M03','test'); p=run.save_figure(fig,'test.png'); run.finish()
    assert p.read_bytes().startswith(b'\x89PNG')
