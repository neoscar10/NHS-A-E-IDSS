"""Notebook execution modes for the NHS A&E analytical workflow."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from src.utils.evidence_exporter import MILESTONES

STAGES = {1: ('M01', 'M02'), 2: ('M03',), 3: ('M04',), 4: ('M05',), 5: ('M06',)}
MODES = ('explore', 'rebuild', 'snapshot')
RUN_ID = re.compile(r'\d{8}T\d{6}Z_[0-9a-f]+')
MARKER = '.ae-rebuild.json'
OWNER = 'nhs-ae-idss-rebuild-v1'


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _runs(repo, milestone):
    root = repo / 'docs/evidence' / MILESTONES[milestone]
    if root.resolve() != root:
        raise ValueError('Evidence directory must not redirect through symlinks')
    return sorted(p.name for p in root.iterdir() if p.is_dir() and RUN_ID.fullmatch(p.name)) if root.is_dir() else []


def _manifest(repo, milestone, run_id):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError('Invalid evidence run ID')
    folder = repo / 'docs/evidence' / MILESTONES[milestone] / run_id
    if folder.resolve() != folder:
        raise ValueError('Evidence run must not redirect through symlinks')
    m = _json(folder / 'evidence_manifest.json')
    if m.get('milestone') != milestone or m.get('run_id') != run_id or m.get('status') != 'COMPLETE':
        raise ValueError(f'{milestone} run {run_id} is not complete; select a verified run')
    if any(t.get('exit_code') != 0 for t in m.get('test_runs', [])):
        raise ValueError(f'{milestone} run contains failed tests')
    return folder, m


def _workspace(project):
    work = project / '.work' / 'rebuild'
    if work.resolve() != work:
        raise ValueError('Rebuild workspace must not redirect through symlinks')
    return work


def _state(work):
    marker = work / MARKER
    if not marker.is_file() or marker.is_symlink():
        raise ValueError('Rebuild directory is not an owned workspace; no files were removed')
    s = _json(marker)
    if s.get('owner') != OWNER or type(s.get('completed')) is not int or not 0 <= s['completed'] <= 5:
        raise ValueError('Invalid rebuild workspace marker')
    return s


def _write_state(work, completed, active=None):
    (work / MARKER).write_text(json.dumps({'owner': OWNER, 'completed': completed, 'active': active}, indent=2) + '\n', encoding='utf-8')


class NotebookSession:
    """Read archived evidence or use one explicit working location for a live stage."""

    def __init__(self, project, mode, stage, *, reset_rebuild=False, view_rebuild=False, run_ids=None):
        self.project = Path(project).resolve()
        if mode not in MODES or type(stage) is not int or stage not in STAGES:
            raise ValueError('Select explore, rebuild or snapshot and a valid notebook stage')
        if not (self.project / 'src/data/data_ingestion.py').is_file():
            raise FileNotFoundError('Open the project repository before running the notebook')
        if reset_rebuild and (mode != 'rebuild' or stage != 1):
            raise ValueError('Reset is allowed only in notebook 01 with rebuild mode')
        if view_rebuild and mode != 'explore':
            raise ValueError('VIEW_REBUILD is available only in explore mode')
        self.mode, self.stage, self.repo = mode, stage, self.project
        self.selected = {}
        if mode == 'explore':
            if view_rebuild:
                self.repo = _workspace(self.project)
                state = _state(self.repo)
                if state['completed'] < stage or state.get('active') is not None:
                    raise ValueError('The requested rebuild stage is not complete')
            for m in STAGES[stage]:
                runs = _runs(self.repo, m)
                run_id = (run_ids or {}).get(m) or (runs[-1] if runs else None)
                if run_id is None:
                    raise FileNotFoundError(f'No saved {m} evidence; create a snapshot or rebuild first')
                self.selected[m] = _manifest(self.repo, m, run_id)
            return
        if run_ids:
            raise ValueError('EXPLORE_RUN_IDS is available only in explore mode')
        if mode == 'rebuild':
            self.repo = _workspace(self.project)
            if stage == 1:
                if self.repo.exists():
                    _state(self.repo)
                    if not reset_rebuild:
                        raise FileExistsError('Rebuild already exists. Explore it or set RESET_REBUILD=True in notebook 01.')
                    shutil.rmtree(self.repo)
                self.repo.mkdir(parents=True, exist_ok=False)
                _write_state(self.repo, 0, 1)
                for rel in ('data/raw', 'src', 'tests', 'notebooks'):
                    shutil.copytree(self.project / rel, self.repo / rel,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.ipynb_checkpoints'))
            else:
                state = _state(self.repo)
                if state['completed'] != stage - 1 or state.get('active') is not None:
                    raise ValueError('Run rebuild notebooks in order once. Restart at notebook 01 to reset an interrupted rebuild.')
                _write_state(self.repo, stage - 1, stage)
        self.before = {m: set(_runs(self.repo, m)) for m in STAGES[stage]}

    def finish(self):
        if self.mode == 'explore':
            return
        for m in STAGES[self.stage]:
            new = set(_runs(self.repo, m)) - self.before[m]
            if len(new) != 1:
                raise RuntimeError(f'Expected exactly one new {m} evidence run')
            _manifest(self.repo, m, new.pop())
        if self.mode == 'rebuild':
            state = _state(self.repo)
            if state.get('active') != self.stage or state['completed'] != self.stage - 1:
                raise RuntimeError('Rebuild stage changed during execution')
            _write_state(self.repo, self.stage)

    def locations(self):
        return {m: folder.relative_to(self.project).as_posix() for m, (folder, _) in self.selected.items()}

    def artifact(self, milestone, relative, *, optional=False):
        folder, manifest = self.selected[milestone]
        entry = manifest['artifacts'].get(relative)
        if entry is None:
            if optional:
                return None
            raise FileNotFoundError(f'Artifact not recorded in {milestone}: {relative}')
        p = (folder / relative).resolve()
        if not p.is_relative_to(folder) or not p.is_file():
            raise FileNotFoundError(f'Artifact not available: {relative}')
        raw = p.read_bytes()
        hashes = [hashlib.sha256(raw).hexdigest()]
        if p.suffix in ('.csv', '.json', '.md', '.txt'):
            # Git may normalise text line endings on different operating systems.
            lf = raw.replace(b'\r\n', b'\n')
            hashes.extend(hashlib.sha256(v).hexdigest() for v in (lf, lf.replace(b'\n', b'\r\n')))
        if entry['sha256'] not in hashes:
            raise ValueError(f'Artifact fingerprint mismatch: {relative}')
        return p

    def show(self, milestone, relative, *, optional=False):
        import pandas as pd
        from IPython.display import display, Image, Markdown
        p = self.artifact(milestone, relative, optional=optional)
        if p is None:
            display(Markdown('No figure was recorded for this run.'))
        elif p.suffix == '.png':
            display(Image(data=p.read_bytes(), width=850))
        elif p.suffix == '.md':
            display(Markdown(p.read_text(encoding='utf-8')))
        elif p.suffix == '.csv':
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
            display(df.head(12))
            print(f'{len(df):,} rows in the saved report; up to 12 displayed.')
        elif p.suffix == '.json':
            value = _json(p)
            fields = {k: v for k, v in value.items() if isinstance(v, (str, int, float, bool)) or v is None}
            fields.update({k: v for k, v in value.get('checks', {}).items() if isinstance(v, (str, int, float, bool))})
            display(pd.DataFrame(fields.items(), columns=['Measure', 'Recorded value']))
        else:
            raise ValueError('Unsupported evidence format')
