"""Notebook execution modes for the NHS A&E analytical workflow."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from uuid import uuid4
from pathlib import Path

from src.utils.evidence_exporter import MILESTONES
from src.data.source_integrity import REGISTER, verify_source_register

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


def _write_state(work, completed, active=None, **extra):
    payload = {'owner': OWNER, 'completed': completed, 'active': active, **extra}
    temp = work / (MARKER + '.tmp')
    temp.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temp.replace(work / MARKER)


def _code_signature(repo):
    paths = sorted(p for folder in ('src', 'tests') for p in (repo / folder).rglob('*.py'))
    paths.extend(p for p in (repo / 'requirements.txt', repo / REGISTER) if p.is_file())
    value = [(p.relative_to(repo).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
    return hashlib.sha256(json.dumps(value).encode('utf-8')).hexdigest()


def _snapshot_workspace(project):
    path = project / '.work/snapshot'
    if path.resolve() != path:
        raise ValueError('Snapshot state directory must not redirect through symlinks')
    return path


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
        self.identity = verify_source_register(self.project)
        self.code_signature = _code_signature(self.project)
        self.work = _workspace(self.project) if mode == 'rebuild' else _snapshot_workspace(self.project)
        if mode == 'rebuild':
            self.repo = self.work
            if stage == 1:
                if self.repo.exists():
                    _state(self.repo)
                    if not reset_rebuild:
                        raise FileExistsError('Rebuild already exists. Explore it or set RESET_REBUILD=True in notebook 01.')
                    shutil.rmtree(self.repo)
                self.repo.mkdir(parents=True, exist_ok=False)
                for rel in ('data/raw', 'src', 'tests', 'notebooks'):
                    shutil.copytree(self.project / rel, self.repo / rel,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.ipynb_checkpoints'))
                (self.repo / REGISTER).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.project / REGISTER, self.repo / REGISTER)
                if (self.project / 'requirements.txt').is_file():
                    shutil.copy2(self.project / 'requirements.txt', self.repo / 'requirements.txt')
        if stage == 1:
            self.work.mkdir(parents=True, exist_ok=True)
            if (self.work / MARKER).exists():
                _state(self.work)
            self.chain = {'workflow_id': uuid4().hex, 'code_signature': self.code_signature,
                          'source_identity': self.identity, 'runs': {}}
        else:
            state = _state(self.work)
            if state['completed'] != stage - 1 or state.get('active') is not None:
                raise ValueError('Run live notebooks in order once; restart at notebook 01 after stopping active kernels.')
            self.chain = {k: state[k] for k in ('workflow_id', 'code_signature', 'source_identity', 'runs')}
        self._check_chain()
        _write_state(self.work, stage - 1, stage, **self.chain)
        self.before = {m: set(_runs(self.repo, m)) for m in STAGES[stage]}

    def finish(self):
        if self.mode == 'explore':
            return
        self._check_chain()
        for m in STAGES[self.stage]:
            new = set(_runs(self.repo, m)) - self.before[m]
            if len(new) != 1:
                raise RuntimeError(f'Expected exactly one new {m} evidence run')
            run_id = new.pop()
            folder, _ = _manifest(self.repo, m, run_id)
            self.chain['runs'][m] = {'run_id': run_id, 'manifest_sha256': hashlib.sha256((folder / 'evidence_manifest.json').read_bytes()).hexdigest()}
        state = _state(self.work)
        if state.get('active') != self.stage or state['completed'] != self.stage - 1 or state.get('workflow_id') != self.chain['workflow_id']:
            raise RuntimeError('Live sequence changed during execution')
        _write_state(self.work, self.stage, **self.chain)

    def _check_chain(self):
        if (_code_signature(self.project) != self.chain['code_signature'] or
                _code_signature(self.repo) != self.chain['code_signature']):
            raise ValueError('Code or dependencies changed during the live sequence; restart at notebook 01')
        if (verify_source_register(self.project) != self.chain['source_identity'] or
                verify_source_register(self.repo) != self.chain['source_identity']):
            raise ValueError('Source baseline changed during the live sequence; restart at notebook 01')
        for m, info in self.chain['runs'].items():
            folder, _ = _manifest(self.repo, m, info['run_id'])
            if hashlib.sha256((folder / 'evidence_manifest.json').read_bytes()).hexdigest() != info['manifest_sha256']:
                raise ValueError(f'Earlier evidence manifest changed: {m}')

    def prior_run(self, milestone):
        if self.mode == 'explore' or milestone not in self.chain['runs']:
            raise ValueError(f'No prior live run for {milestone}')
        return self.chain['runs'][milestone]['run_id']

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
