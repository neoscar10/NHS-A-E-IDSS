"""Versioned research evidence snapshots for the NHS A&E IDSS project.

Only writes under docs/evidence. No data cleaning or model training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

MILESTONES = {
    'M01': 'M01_Data_Inventory', 'M02': 'M02_Data_Ingestion',
    'M03': 'M03_Data_Quality', 'M04': 'M04_Preprocessing',
    'M05': 'M05_Longitudinal_Preparation', 'M06': 'M06_Final_Dataset',
    'M07': 'M07_Feature_Engineering', 'M08': 'M08_Model_Development',
    'M09': 'M09_Model_Evaluation', 'M10': 'M10_IDSS_Application',
}
M01_REPORTS = ('docs/source_manifest.csv', 'docs/m01_coverage.json')
M02_REPORTS = ('data/staging/m02_ingestion_summary.json',)
M03_REPORTS = ('docs/m03_quality_summary.json', 'docs/m03_quality_report.md',
               'data/quality/m03_findings.csv', 'docs/m03_monthly_profile.csv',
               'docs/m03_monthly_reconciliation.csv', 'docs/m03_provider_continuity.csv',
               'docs/m03_type1_change_candidates.csv')
STAGED = ('data/staging/ae_historical_raw_combined.csv',
          'data/staging/ae_historical_raw_combined.parquet')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def find_repo(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for p in (start, *start.parents):
        if (p / 'src/data/data_ingestion.py').is_file() and (p / 'data/raw').is_dir():
            return p
    raise FileNotFoundError('Open the NHS-A-E-IDSS repository and run from that folder or notebooks/.')


def _git_revision(repo: Path) -> str | None:
    try:
        p = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class EvidenceRun:
    """Create a new run, capture exact inputs and artifacts, and seal a manifest.

    Run IDs are UTC plus a random suffix. Completed runs are never reused by
    this utility. An interrupted run has status IN_PROGRESS, not COMPLETE.
    """
    def __init__(self, repo: Path, milestone: str, purpose: str):
        if milestone not in MILESTONES:
            raise ValueError(f'Unknown milestone: {milestone}')
        self.repo = Path(repo).resolve()
        if not (self.repo / 'src/data/data_ingestion.py').is_file():
            raise FileNotFoundError('Expected existing project src/data/data_ingestion.py')
        self.milestone = milestone
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
        evidence_root = self.repo / 'docs/evidence'
        # Reject symlink redirection outside the expected project evidence area.
        if evidence_root.resolve() != evidence_root or (evidence_root / MILESTONES[milestone]).resolve() != evidence_root / MILESTONES[milestone]:
            raise ValueError('Evidence destination must not redirect through symlinks')
        self.path = evidence_root / MILESTONES[milestone] / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        for sub in ('figures', 'reports', 'test_results'):
            (self.path / sub).mkdir()
        self.inputs = {}
        self.copies = {}
        self.test_results = []
        self.sealed = False
        packages = {}
        for name in ('pandas', 'pyarrow', 'matplotlib', 'pytest', 'ipykernel'):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = None
        self.metadata = {'milestone': milestone, 'run_id': self.run_id,
                         'purpose': purpose, 'created_utc': utc_now(),
                         'git_head': _git_revision(self.repo),
                         'git_note': 'HEAD alone does not identify uncommitted changes; use input hashes.',
                         'python': platform.python_version(), 'packages': packages}
        self._manifest('IN_PROGRESS')

    def _open(self):
        if self.sealed:
            raise RuntimeError('Evidence run already sealed; create a new snapshot.')

    def _source(self, relative: str) -> Path:
        p = (self.repo / relative).resolve()
        if not p.is_relative_to(self.repo) or not p.is_file():
            raise FileNotFoundError(f'Expected project file: {relative}')
        return p

    def _dest(self, relative: str) -> Path:
        self._open()
        p = (self.path / relative).resolve()
        if not p.is_relative_to(self.path) or p == self.path or p.name == 'evidence_manifest.json':
            raise ValueError('Destination must be a file inside this run')
        if p.exists():
            raise FileExistsError(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def record_input(self, relative: str, required: bool = True):
        """Record data/code fingerprints, without duplicating large data files."""
        self._open()
        try:
            p = self._source(relative)
        except FileNotFoundError:
            if required:
                raise
            self.inputs[relative] = {'status': 'NOT_PRESENT'}
            return
        key = p.relative_to(self.repo).as_posix()
        self.inputs[key] = {'status': 'PRESENT', 'bytes': p.stat().st_size, 'sha256': digest(p)}

    def copy_report(self, relative: str) -> Path:
        src = self._source(relative)
        self.record_input(relative)
        dest = self._dest('reports/' + src.name)
        shutil.copyfile(src, dest)
        key = src.relative_to(self.repo).as_posix()
        if digest(dest) != self.inputs[key]['sha256']:
            raise RuntimeError(f'Source changed during copy: {relative}')
        self.copies[dest.relative_to(self.path).as_posix()] = key
        return dest

    def save_figure(self, fig, filename: str) -> Path:
        """Save an editable notebook figure as a high-resolution PNG."""
        if Path(filename).name != filename or not filename.lower().endswith('.png'):
            raise ValueError('Use a simple .png filename')
        dest = self._dest('figures/' + filename)
        fig.savefig(dest, dpi=300, bbox_inches='tight', facecolor='white')
        return dest

    def write_text(self, relative: str, text: str) -> Path:
        p = self._dest(relative)
        p.write_text(text, encoding='utf-8')
        return p

    def write_table(self, relative: str, dataframe) -> Path:
        p = self._dest(relative)
        dataframe.to_csv(p, index=False)
        return p

    def run_tests(self, *test_paths: str) -> int:
        self._open()
        for path in test_paths:
            self.record_input(path)
        args = [sys.executable, '-m', 'pytest', '-q', *test_paths]
        start = utc_now()
        try:
            p = subprocess.run(args, cwd=self.repo, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=300)
            rc, output = p.returncode, p.stdout + '\n' + p.stderr
        except subprocess.TimeoutExpired as exc:
            rc, output = 124, f'Test run timed out after 300 seconds.\n{exc}'
        except OSError as exc:
            rc, output = 125, f'Test launch failed: {exc}'
        log = f'UTC: {start}\nCommand: python -m pytest -q {" ".join(test_paths)}\nExit code: {rc}\n\n{output}'
        self.write_text(f'test_results/pytest_{len(self.test_results)+1:02d}.txt', log)
        self.test_results.append({'tests': list(test_paths), 'exit_code': rc, 'started_utc': start})
        return rc

    def _manifest(self, status: str, note: str = ''):
        artifacts = {}
        for p in sorted(self.path.rglob('*')):
            if p.is_file() and p.name != 'evidence_manifest.json':
                rel = p.relative_to(self.path).as_posix()
                artifacts[rel] = {'sha256': digest(p), 'bytes': p.stat().st_size}
                if rel in self.copies:
                    artifacts[rel]['copied_from'] = self.copies[rel]
        value = {**self.metadata, 'status': status, 'note': note,
                 'inputs': self.inputs, 'artifacts': artifacts, 'test_runs': self.test_results}
        if status != 'IN_PROGRESS':
            value['finished_utc'] = utc_now()
        (self.path / 'evidence_manifest.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

    def finish(self, note: str = '', review_required: bool = False) -> Path:
        self._open()
        # Detect input changes during collection (including source reports).
        changed = []
        for relative, info in self.inputs.items():
            p = self.repo / relative
            if info['status'] == 'PRESENT' and (not p.is_file() or digest(p) != info['sha256']):
                changed.append(relative)
            elif info['status'] == 'NOT_PRESENT' and p.exists():
                changed.append(relative)
        if changed:
            note += '\nInputs changed during snapshot: ' + ', '.join(changed)
        status = 'COMPLETE_REVIEW_REQUIRED' if review_required or changed or any(t['exit_code'] for t in self.test_results) else 'COMPLETE'
        self._manifest(status, note)
        self.sealed = True
        return self.path


def record_common_inputs(run: EvidenceRun, include_staged: bool = False):
    for p in ('src/data/data_ingestion.py', 'src/utils/evidence_exporter.py', *M01_REPORTS):
        run.record_input(p)
    for p in ('docs/source_baseline.json', 'src/data/source_integrity.py'):
        run.record_input(p, required=False)
    if include_staged:
        for p in (*M02_REPORTS, *STAGED):
            run.record_input(p, required=p in M02_REPORTS)
        if not any((run.repo / p).is_file() for p in STAGED):
            raise FileNotFoundError('No staged dataset found. Run M01/M02 first.')


def snapshot_existing(repo: Path, milestone: str, run_tests: bool = False) -> Path:
    """Reports-only archival of current local files, not a fresh validation."""
    groups = {'M01': M01_REPORTS, 'M02': M02_REPORTS, 'M03': M03_REPORTS}
    tests = {'M01': 'tests/test_data_ingestion.py', 'M02': 'tests/test_data_ingestion.py', 'M03': 'tests/test_data_validation.py'}
    if milestone not in groups:
        raise ValueError('The reports-only CLI currently supports M01 to M03')
    run = EvidenceRun(repo, milestone, 'Archive existing output files; original run time is not asserted.')
    record_common_inputs(run, milestone != 'M01')
    if milestone == 'M03':
        run.record_input('src/data/data_validation.py')
    for path in groups[milestone]:
        run.copy_report(path)
    if run_tests:
        run.run_tests(tests[milestone])
    summary = json.loads((repo / groups[milestone][0 if milestone != 'M01' else 1]).read_text(encoding='utf-8'))
    review = (bool(summary.get('missing_months') or summary.get('duplicate_months') or summary.get('unexpected_months') or summary.get('preliminary_review_files')) if milestone == 'M01'
              else summary.get('quality_gate') == 'REVIEW_REQUIRED' if milestone == 'M03' else False)
    return run.finish('Existing reports copied byte-for-byte; input hashes describe files at collection time, not proof of historical execution. Figures require the notebook. Tests are new runs if requested.', review)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--milestone', nargs='+', choices=['M01', 'M02', 'M03'], required=True)
    parser.add_argument('--run-tests', action='store_true')
    args = parser.parse_args()
    for milestone in dict.fromkeys(args.milestone):
        print(snapshot_existing(args.repo.resolve(), milestone, args.run_tests))


if __name__ == '__main__':
    main()
