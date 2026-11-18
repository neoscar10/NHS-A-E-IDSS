"""M04: deterministic standardisation and separation of mixed-grain NHS A&E data.
Run from repository root: python -m src.data.data_preprocessing --repo .
M05, not M04, defines longitudinal continuity and modelling eligibility.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

from src.data.data_ingestion import EXPECTED_COLUMNS, period_month
from src.data.data_validation import PROVENANCE, MEASURES, load_staged, is_total_series, validate_dataset
from src.utils.evidence_exporter import EvidenceRun, digest, record_common_inputs

MEASURE_NAMES = [
    'type1_attendances', 'type2_attendances', 'other_attendances',
    'type1_booked_attendances', 'type2_booked_attendances', 'other_booked_attendances',
    'type1_over_4hrs', 'type2_over_4hrs', 'other_over_4hrs',
    'type1_booked_over_4hrs', 'type2_booked_over_4hrs', 'other_booked_over_4hrs',
    'dta_wait_4_12hrs', 'dta_wait_12plus_hrs',
    'type1_emergency_admissions', 'type2_emergency_admissions',
    'other_ae_emergency_admissions', 'other_emergency_admissions',
]
RENAME = dict(zip(EXPECTED_COLUMNS, ['source_period', 'org_code', 'parent_org', 'org_name'] + MEASURE_NAMES))
TARGET = 'type1_attendances'
OUTPUT_COLUMNS = ['period', *RENAME.values(), *PROVENANCE]


def standardise(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Preserve every row and source count; only change representation and grain."""
    if list(data.columns) != EXPECTED_COLUMNS + PROVENANCE:
        raise ValueError('Unexpected M02 schema')
    source = data.astype('string').fillna('')
    totals = is_total_series(source)
    clean = source.rename(columns=RENAME).copy()
    months = clean['source_month']
    if not months.str.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])').all():
        raise ValueError('Invalid source_month')
    if not source.loc[~totals, 'Period'].map(period_month).eq(months.loc[~totals]).all():
        raise ValueError('Provider reporting period mismatch')
    clean['period'] = pd.to_datetime(months + '-01', format='%Y-%m-%d', errors='raise')
    changes = []
    for field in ('org_code', 'org_name', 'parent_org'):
        original = clean[field].copy()
        clean[field] = original.str.strip()
        if field == 'org_code':
            clean[field] = clean[field].str.upper()
        changes.append({'field': field, 'rows_standardised': int(original.ne(clean[field]).sum()),
                        'operation': 'trim and uppercase' if field == 'org_code' else 'trim outer whitespace'})
    # No provider names are merged or overwritten. Keep each observed name.
    for field in MEASURE_NAMES:
        values = clean[field].str.strip()
        if not values.str.fullmatch(r'[0-9]+').all():
            raise ValueError(f'Invalid published count in {field}; do not impute')
        ints = values.map(int)
        if any(n > 2**63 - 1 for n in ints):
            raise ValueError(f'Count exceeds signed int64 range in {field}')
        clean[field] = ints.astype('int64')
    # Use the same aggregate detection as M03; no provider eligibility filter.
    provider = clean.loc[~totals, OUTPUT_COLUMNS].copy()
    national = clean.loc[totals, OUTPUT_COLUMNS].copy()
    if provider.empty or national.empty:
        raise ValueError('Expected provider and national records')
    if provider[['org_code','org_name']].eq('').any().any():
        raise ValueError('Missing provider identity')
    if provider.duplicated(['period','org_code']).any():
        raise ValueError('Duplicate provider-month key')
    if national.duplicated('period').any() or set(national.period) != set(provider.period):
        raise ValueError('Expected exactly one national total per provider reporting month')
    for col in MEASURE_NAMES:
        # Python integer arithmetic avoids silent overflow in conservation checks.
        for m, frame in provider.groupby('period', sort=True):
            match = national.loc[national.period.eq(m), col].iloc[0]
            if sum(map(int, frame[col])) != int(match):
                raise ValueError(f'National total mismatch: {m:%Y-%m} {col}')
        if sum(map(int, clean[col])) != sum(map(int, provider[col])) + sum(map(int, national[col])):
            raise AssertionError(f'Count conservation failed: {col}')
    if len(provider) + len(national) != len(source):
        raise AssertionError('Row conservation failed')
    for frame in (provider, national):
        frame.sort_values(['period','org_code','source_file','source_record_number'], kind='stable', inplace=True)
        frame.reset_index(drop=True, inplace=True)
    return provider, national, pd.DataFrame(changes)


def data_dictionary() -> pd.DataFrame:
    rows = [{'field':'period','source':'source_month','dtype':'datetime64 (month start)','definition':'Reporting month, not an attendance timestamp.'}]
    for raw, field in RENAME.items():
        detail = 'Published count; no change in numeric value.' if raw in MEASURES else {
            'Period':'Original period text, including TOTAL labels.', 'Org Code':'Trimmed, uppercased source organisation code; not a numeric feature.',
            'Org name':'Observed organisation name, outer spaces trimmed; variants preserved.',
            'Parent Org':'Observed parent grouping, outer spaces trimmed; not a verified historical crosswalk.'}[raw]
        rows.append({'field':field,'source':raw,'dtype':'int64' if raw in MEASURES else 'string','definition':detail})
    for field in PROVENANCE:
        rows.append({'field':field,'source':field,'dtype':'string','definition':'Unchanged M02 source traceability field.'})
    return pd.DataFrame(rows)


def conservation(data: pd.DataFrame, provider: pd.DataFrame, national: pd.DataFrame) -> pd.DataFrame:
    total = is_total_series(data.astype('string').fillna(''))
    records = []
    for raw, field in zip(MEASURES, MEASURE_NAMES):
        before_p = sum(map(int, data.loc[~total, raw].str.strip()))
        before_n = sum(map(int, data.loc[total, raw].str.strip()))
        after_p = sum(map(int, provider[field])); after_n = sum(map(int, national[field]))
        records.append({'measure':field,'provider_before':before_p,'provider_after':after_p,
                        'national_before':before_n,'national_after':after_n,
                        'provider_difference':after_p-before_p,'national_difference':after_n-before_n,
                        'status':'MATCH' if (before_p, before_n)==(after_p, after_n) else 'MISMATCH'})
    return pd.DataFrame(records)


def make_figures(summary: dict, changes: pd.DataFrame, provider: pd.DataFrame):
    """Return editable Matplotlib figures, using actual computed results."""
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig, ax = plt.subplots(figsize=(9,3.6), layout='constrained')
    p,n=summary['provider_rows'],summary['national_rows']
    ax.barh(['M02: mixed source','M04: separated outputs'], [p,p], color='#22658a', label='Provider records')
    ax.barh(['M02: mixed source','M04: separated outputs'], [n,n], left=[p,p], color='#d18b3f', label=f'National totals ({n:,} records)')
    ax.invert_yaxis(); ax.set_xlabel('Records (national totals retained separately)')
    ax.set_title(f'Every source record is accounted for: {p+n:,} records',loc='left',fontweight='bold')
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.21),ncol=2,frameon=False)
    ax.set_xlim(0,(p+n)*1.08)
    for i in range(2): ax.text(p/2,i,f'{p:,} provider',ha='center',va='center',color='white',fontweight='bold')
    yield '01_record_conservation.png',fig
    fig, ax = plt.subplots(figsize=(9,3.6),layout='constrained')
    ax.barh(changes['field'],changes['rows_standardised'],color='#25877d')
    ax.invert_yaxis(); ax.set_xlabel('Rows whose text representation changed')
    ax.set_title('Identifier standardisation changes formatting, not provider identities',loc='left',fontweight='bold',fontsize=11)
    xmax=max(1,int(changes.rows_standardised.max()))
    ax.set_xlim(0,xmax*1.25)
    for i,v in enumerate(changes.rows_standardised): ax.text(v+xmax*.02,i,f'{v:,}',va='center')
    ax.grid(axis='x',alpha=.18)
    yield '02_identifier_standardisation.png',fig
    profile = provider.groupby('period',sort=True)[TARGET].agg(records='size',zero=lambda x:int(x.eq(0).sum())).reset_index()
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    ax.plot(profile.period,100*profile.zero/profile.records,color='#22658a',linewidth=2,marker='o',markersize=2.5)
    ax.set_ylim(0,100);ax.set_ylabel('Provider records with zero Type 1 (%)');ax.set_xlabel('Reporting month')
    ax.set_title('Reported zero Type 1 activity is retained for cohort review',loc='left',fontweight='bold')
    ax.grid(axis='y',alpha=.2)
    yield '03_zero_type1_preserved.png',fig


def run_preprocessing(repo: Path, *, run_tests: bool = True, notebook: bool = False) -> dict:
    repo=Path(repo).resolve()
    run=EvidenceRun(repo,'M04','Standardise NHS source representations and separate provider and national records.')
    try:
        record_common_inputs(run, include_staged=True)
        for rel in ('src/data/data_validation.py','src/data/data_preprocessing.py'):
            run.record_input(rel)
        if notebook:
            run.record_input('notebooks/03_data_preprocessing.ipynb')
        # Confirm source inputs still match the original M01 fingerprint register.
        manifest=pd.read_csv(repo/'docs/source_manifest.csv',dtype=str,keep_default_na=False)
        for row in manifest.to_dict('records'):
            rel=row['source_file']
            if not rel.startswith('data/raw/'):
                raise ValueError('Unexpected source path in M01 manifest')
            run.record_input(rel)
            if run.inputs[rel]['sha256'] != row['sha256']:
                raise ValueError(f'Raw source changed after M01: {rel}; repeat M01 to M03')
        data, input_path=load_staged(repo)
        # Fresh M03 checks against the very same input, in this evidence run only.
        audit=validate_dataset(repo,input_path=input_path,output_root=run.path/'reports/m03_revalidation')
        checks=audit['summary']['checks']
        if audit['summary']['quality_gate']!='PASS_CORE_CHECKS_WITH_ADVISORIES' or any(checks[k]!='MATCH' for k in ('m02_row_count_check','m01_manifest_check','m01_month_coverage_check')):
            raise ValueError('M03 core or input-lineage checks require review; inspect revalidation reports')
        provider,national,changes=standardise(data)
        preserved=conservation(data,provider,national)
        if not preserved.status.eq('MATCH').all():
            raise AssertionError('Original numeric measures changed')
        rc=run.run_tests('tests/test_data_preprocessing.py') if run_tests else None
        if rc not in (None,0):
            raise RuntimeError('M04 tests did not pass; inspect test_results')
        # Confirm inputs remained unchanged prior to publishing processed outputs.
        for rel,info in run.inputs.items():
            p=repo/rel
            if info['status']=='PRESENT' and (not p.is_file() or digest(p)!=info['sha256']):
                raise RuntimeError(f'Input changed during M04: {rel}')
            if info['status']=='NOT_PRESENT' and p.exists():
                raise RuntimeError(f'Input appeared during M04: {rel}')
        dest=repo/'data/processed/m04'/run.run_id
        if dest.resolve()!=dest:
            raise ValueError('Processed destination must not redirect through symlinks')
        dest.mkdir(parents=True,exist_ok=False)
        outputs={}
        parquet_available=importlib.util.find_spec('pyarrow') is not None
        for label,frame in [('ae_provider_monthly',provider),('ae_national_monthly',national)]:
            csv=dest/f'{label}.csv';frame.to_csv(csv,index=False,date_format='%Y-%m-%d')
            outputs[csv.relative_to(repo).as_posix()]={'sha256':digest(csv),'rows':len(frame)}
            if parquet_available:
                pq=dest/f'{label}.parquet';frame.to_parquet(pq,index=False,engine='pyarrow')
                outputs[pq.relative_to(repo).as_posix()]={'sha256':digest(pq),'rows':len(frame)}
        summary={'status':'PASS_STANDARDISATION','run_id':run.run_id,
                 'input':input_path.relative_to(repo).as_posix(),'input_sha256':digest(input_path),
                 'input_rows':len(data),'provider_rows':len(provider),'national_rows':len(national),
                 'provider_rows_removed':0,'records_unaccounted_for':len(data)-len(provider)-len(national),
                 'months':int(provider.period.nunique()),'provider_codes':int(provider.org_code.nunique()),
                 'output_columns':len(OUTPUT_COLUMNS),'counts_preserved':int(preserved.status.eq('MATCH').sum()),
                 'zero_type1_before':int((data.loc[~is_total_series(data), MEASURES[0]].str.strip().map(int)==0).sum()),
                 'zero_type1_after':int(provider[TARGET].eq(0).sum()),'m03_checks':checks,
                 'parquet_status':'exported' if parquet_available else 'not available; CSV exported',
                 'tests_exit_code':rc,'output_directory':dest.relative_to(repo).as_posix(),'outputs':outputs}
        assert summary['zero_type1_before']==summary['zero_type1_after']
        decisions=pd.DataFrame([
            ['Reporting month','Create period as first day of source_month; retain source_period','M04','Implemented'],
            ['Mixed grain','Separate national TOTAL rows from providers; preserve both outputs','M04','Implemented'],
            ['18 published measures','Convert losslessly to non-negative int64; no scaling or imputation','M04','Implemented'],
            ['Organisation identities','Trim text, uppercase codes; do not merge codes or names','M04','Implemented'],
            ['Reported zeros','Retain all zero observations; never fill absent rows with zero','M04','Implemented'],
            ['Missing provider-months, names and large changes','Investigate continuity and source context','M05','Pending'],
            ['Type 1 cohort','Define eligibility using history available at each forecast origin','M05/M07','Pending'],
        ],columns=['finding','decision','stage','status'])
        run.write_table('reports/m04_data_dictionary.csv',data_dictionary())
        run.write_table('reports/m04_measure_conservation.csv',preserved)
        run.write_table('reports/m04_identifier_changes.csv',changes)
        run.write_table('reports/m04_decisions.csv',decisions)
        run.write_text('reports/m04_summary.json',json.dumps(summary,indent=2)+'\n')
        run.write_text('reports/m04_research_report.md',f'''# M04 | Cleaning and standardisation\n\n## Objective\nCreate a typed provider-month dataset while preserving source counts and national totals.\n\n## Results\n- {len(data):,} input records became {len(provider):,} provider records and {len(national):,} national records. No source records were discarded.\n- {summary['months']} reporting months; {summary['counts_preserved']} of 18 measures conserved in both row groups.\n- {summary['zero_type1_after']:,} provider records with zero Type 1 activity retained.\n- Fresh M03 validation passed its implemented core checks.\n\n## Interpretation and decision\nThe national aggregate is a separate grain, not a provider. Separating it prevents double-counting while retaining a benchmark. Date and identifier formatting establish a consistent key, not proof that organisations are historically comparable. Zeros are reported values, not missing records. No gap filling, provider merging, outlier removal, model training or cohort restriction has been performed. M05 must investigate provider continuity, service eligibility and gaps before feature engineering.\n\nSource: https://github.com/neoscar10/NHS-A-E-IDSS (local M02 staged export; fingerprint in summary).\n''')
        for filename,fig in make_figures(summary,changes,provider):
            run.save_figure(fig,filename);plt.close(fig)
        (dest/'m04_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        run.record_input((dest/'m04_summary.json').relative_to(repo).as_posix())
        for rel in outputs: run.record_input(rel)
        run.finish('Standardisation complete. M03 advisories remain for M05; no modelling approval.',review_required=rc is None)
        # Consumers should use this run ID only when its evidence manifest is COMPLETE.
        final=json.loads((run.path/'evidence_manifest.json').read_text(encoding='utf-8'))
        return {'summary':summary,'evidence_status':final['status'],'evidence_path':str(run.path),'provider':provider,'national':national,'changes':changes,'conservation':preserved,'decisions':decisions}
    except Exception as exc:
        if not run.sealed:
            run.write_text('reports/m04_failure.txt',f'{type(exc).__name__}: {exc}\n')
            run.finish('M04 failed; any partial outputs must not be used.',review_required=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    args=parser.parse_args()
    result=run_preprocessing(args.repo)
    print(json.dumps({'summary':result['summary'],'evidence_status':result['evidence_status'],'evidence_path':result['evidence_path']},indent=2))
    if result['evidence_status']!='COMPLETE': raise SystemExit(2)

if __name__=='__main__': main()
