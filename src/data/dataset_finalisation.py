"""Verify longitudinal preparation and publish a versioned analytical dataset."""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
from io import StringIO
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from src.data.data_preprocessing import OUTPUT_COLUMNS, MEASURE_NAMES, TARGET, data_dictionary
from src.data.longitudinal_preparation import read_m04, typed, prepare_panel
from src.utils.evidence_exporter import EvidenceRun, digest

RUN_ID = re.compile(r'\d{8}T\d{6}Z_[0-9a-f]+')
PANEL_FIELDS = ['is_observed','observation_state','observed_last_n_months','positive_last_n_months','history_ready','type1_candidate','candidate_status','history_window_months']


def canonical_csv(frame):
    return pd.read_csv(StringIO(frame.to_csv(index=False,date_format='%Y-%m-%d')),dtype='string',keep_default_na=False)


def equal_csv(actual, expected, label):
    try:
        pd.testing.assert_frame_equal(actual.reset_index(drop=True),canonical_csv(expected),check_dtype=False)
    except AssertionError as exc:
        raise ValueError(f'{label} differs from the verified reference') from exc


def read_m05(repo, run_id=None):
    root=repo/'data/processed/m05'
    if run_id is None:
        runs=sorted(p.name for p in root.iterdir() if p.is_dir() and RUN_ID.fullmatch(p.name))
        if not runs: raise FileNotFoundError('No M05 run found')
        run_id=runs[-1]
    if not RUN_ID.fullmatch(run_id): raise ValueError('Invalid M05 run ID')
    folder=root/run_id
    paths=[folder/'m05_summary.json',repo/'docs/evidence/M05_Longitudinal_Preparation'/run_id/'evidence_manifest.json',folder/'ae_provider_calendar.csv']
    s,m=[json.loads(p.read_text(encoding='utf-8')) for p in paths[:2]]
    if s['status']!='PASS_LONGITUDINAL_PREPARATION' or m['status']!='COMPLETE' or s['run_id']!=run_id or m['run_id']!=run_id:
        raise ValueError('M05 run not complete; select a verified M05 run')
    for p in [paths[0], paths[2]]:
        rel=p.relative_to(repo).as_posix()
        if digest(p)!=m['inputs'][rel]['sha256'] or (p==paths[2] and digest(p)!=s['outputs'][rel]['sha256']):
            raise ValueError(f'M05 fingerprint mismatch: {rel}')
    # Verify the declared Parquet fingerprint when present; CSV is the reference representation.
    pq=folder/'ae_provider_calendar.parquet'; rel=pq.relative_to(repo).as_posix()
    if rel in s['outputs']:
        if digest(pq)!=s['outputs'][rel]['sha256'] or digest(pq)!=m['inputs'][rel]['sha256']:
            raise ValueError('M05 Parquet fingerprint mismatch')
        paths.append(pq)
    p,n,s4,p4=read_m04(repo,s['m04_run_id'])
    for path in p4:
        rel=path.relative_to(repo).as_posix()
        if digest(path)!=m['inputs'][rel]['sha256']: raise ValueError(f'M04 input changed after M05: {rel}')
    actual=pd.read_csv(paths[2],dtype='string',keep_default_na=False)
    return actual,p,n,s,s4,paths+p4


def verify_release(actual,provider,national,s5):
    """Reconstruct M05 from its pinned M04 input and verify conservation and eligibility."""
    expected,profile,monthly=prepare_panel(provider,national,s5['history_window_months'])
    equal_csv(actual,expected,'M05 calendar')
    p,n=typed(provider),typed(national)
    p=p.sort_values(['period','org_code']).reset_index(drop=True)
    n=n.sort_values('period').reset_index(drop=True)
    if n.org_code.str.upper().ne('TOTAL').any(): raise ValueError('National dataset contains a non-TOTAL code')
    # Compare the observed calendar to the original provider records field by field.
    observed=expected.loc[expected.is_observed,OUTPUT_COLUMNS].reset_index(drop=True)
    equal_csv(canonical_csv(observed),p,'Observed provider records')
    absent=~expected.is_observed
    checks={'calendar_rows':len(expected),'observed_rows':int(expected.is_observed.sum()),'absent_rows':int(absent.sum()),'reported_zero_rows':int(expected.observation_state.eq('Reported zero').sum()),'candidate_origin_rows':int(expected.type1_candidate.sum()),'reporting_months':len(monthly),'provider_codes':int(expected.org_code.nunique()),'latest_candidates':int(monthly.iloc[-1].candidate_rows),'latest_observed_providers':int(monthly.iloc[-1].observed_rows),'latest_month':monthly.iloc[-1].period.strftime('%Y-%m')}
    for key,val in checks.items():
        if val!=s5[key]: raise ValueError(f'M05 summary mismatch: {key}')
    if expected.loc[absent,MEASURE_NAMES].notna().any().any(): raise ValueError('Absent records contain numeric values')
    # Reconcile all published counts using Python integers to avoid overflow.
    rec=[]
    for period,g in p.groupby('period',sort=True):
        total=n.loc[n.period.eq(period)].iloc[0]
        for field in MEASURE_NAMES:
            provider_sum=sum(map(int,g[field])); published=int(total[field]); diff=provider_sum-published
            rec.append({'period':period,'measure':field,'provider_sum':provider_sum,'national_total':published,'difference':diff,'status':'MATCH' if diff==0 else 'MISMATCH'})
    reconciliation=pd.DataFrame(rec)
    if reconciliation.status.ne('MATCH').any(): raise ValueError('National count reconciliation failed')
    return expected,p,n,profile,monthly,reconciliation,checks


def release_dictionary():
    base=data_dictionary().copy()
    base.loc[base.field.isin(MEASURE_NAMES),'dtype']='nullable Int64 in provider calendar; non-null integer in observed and national exports'
    base.loc[~base.field.isin(['period','org_code',*MEASURE_NAMES]),'definition'] += ' Empty for absent calendar rows; missing source attributes are not inferred.'
    fields=[('is_observed','boolean','True for a published provider record; false for an absent calendar row.'),('observation_state','string','Reported positive, reported zero, or absent record.'),('observed_last_n_months','integer','Count of reported records in trailing history window including origin.'),('positive_last_n_months','integer','Count of positive Type 1 observations in the same window.'),('history_ready','boolean','True if every month of the configured window is observed.'),('type1_candidate','boolean','Provisional origin eligibility from available reporting history; not verified service status.'),('candidate_status','string','Reason for candidate or non-candidate classification at origin.'),('history_window_months','integer','Configured number of consecutive months required.')]
    return pd.concat([base,pd.DataFrame([{'field':k,'source':'M05 derived','dtype':t,'definition':d} for k,t,d in fields])],ignore_index=True)


def figures(panel,monthly,national,reconciliation):
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    ax.barh(['Provider calendar'],[int(panel.is_observed.sum())],color='#22658a',label='Observed records')
    ax.barh(['Provider calendar'],[int((~panel.is_observed).sum())],left=[int(panel.is_observed.sum())],color='#d18b3f',label='Absent records (null counts)')
    ax.set_title(f'Final calendar retains {len(panel):,} provider-month rows',loc='left',fontweight='bold');ax.set_xlabel('Provider-month records');ax.legend(loc='upper center',bbox_to_anchor=(.5,-.2),ncol=2,frameon=False);ax.grid(axis='x',alpha=.18)
    yield '01_final_record_coverage.png',fig
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    ax.plot(monthly.period,monthly.observed_rows,color='#22658a',label='Reported providers',linewidth=2)
    ax.plot(monthly.period,monthly.candidate_rows,color='#25877d',label='Provisional candidates',linewidth=2)
    ax.set(title='Forecasting candidates are a subset of reported providers',xlabel='Reporting month (forecast origin proxy)',ylabel='Provider codes');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2);ax.legend(frameon=False)
    yield '02_candidate_coverage.png',fig
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    type1=reconciliation.loc[reconciliation.measure.eq(TARGET)]
    ax.plot(type1.period,type1.national_total,color='#22658a',linewidth=2.5,label='Published national total')
    ax.plot(type1.period,type1.provider_sum,color='#d18b3f',linestyle='--',linewidth=1.5,label='Sum of observed provider counts')
    ax.set(title='National Type 1 series agrees with summed provider records',xlabel='Reporting month',ylabel='Type 1 attendances');ax.grid(axis='y',alpha=.2);ax.legend(frameon=False);ax.ticklabel_format(axis='y',style='plain')
    yield '03_national_type1_reconciliation.png',fig


def run_finalise(repo, m05_run_id=None, run_tests=True, notebook=False):
    repo=Path(repo).resolve(); ev=EvidenceRun(repo,'M06','Verify and publish a versioned analytical dataset and data contract.')
    try:
        for rel in ('src/data/dataset_finalisation.py','src/data/longitudinal_preparation.py','src/data/data_preprocessing.py','src/utils/evidence_exporter.py'):
            ev.record_input(rel)
        if notebook: ev.record_input('notebooks/05_final_dataset.ipynb')
        actual,p,n,s5,s4,paths=read_m05(repo,m05_run_id)
        for path in paths: ev.record_input(path.relative_to(repo).as_posix())
        panel,p,n,profile,monthly,rec,checks=verify_release(actual,p,n,s5)
        if checks['observed_rows']!=s4['provider_rows'] or len(n)!=s4['national_rows'] or len(p)+len(n)!=s4['input_rows']:
            raise ValueError('M04 source row conservation failed')
        rc=ev.run_tests('tests/test_dataset_finalisation.py') if run_tests else None
        if rc not in (None,0): raise RuntimeError('M06 tests failed')
        dest=repo/'data/processed/m06'/ev.run_id
        if dest.resolve()!=dest: raise ValueError('Invalid output location')
        dest.mkdir(parents=True,exist_ok=False)
        outputs={}; parquet=importlib.util.find_spec('pyarrow') is not None
        for label,frame in [('ae_provider_calendar_final',panel),('ae_provider_observed_final',p),('ae_national_final',n)]:
            path=dest/f'{label}.csv';frame.to_csv(path,index=False,date_format='%Y-%m-%d')
            equal_csv(pd.read_csv(path,dtype='string',keep_default_na=False),frame,label+' CSV round trip')
            outputs[path.relative_to(repo).as_posix()]={'rows':len(frame),'sha256':digest(path)}
            if parquet:
                path=dest/f'{label}.parquet';frame.to_parquet(path,index=False,engine='pyarrow')
                # Compare normalised values, including nullable numbers and booleans.
                equal_csv(canonical_csv(pd.read_parquet(path)),frame,label+' Parquet round trip')
                outputs[path.relative_to(repo).as_posix()]={'rows':len(frame),'sha256':digest(path)}
        summary={'status':'PASS_FINAL_DATASET_VERIFICATION','run_id':ev.run_id,'m05_run_id':s5['run_id'],'m04_run_id':s4['run_id'],**checks,'national_rows':len(n),'first_month':monthly.iloc[0].period.strftime('%Y-%m'),'calendar_columns':len(panel.columns),'original_measures':len(MEASURE_NAMES),'national_comparisons':len(rec),'national_mismatches':int(rec.status.ne('MATCH').sum()),'history_window_months':s5['history_window_months'],'parquet_status':'exported and verified' if parquet else 'CSV only; PyArrow not installed','test_exit_code':rc,'outputs':outputs}
        dictionary=release_dictionary()
        contract={'schema_version':'1.0','calendar_key':['org_code','period'],'observed_key':['org_code','period'],'national_key':['period'],'target_measure':TARGET,'calendar_columns':list(panel.columns),'observed_and_national_columns':OUTPUT_COLUMNS,'missing_counts':'Absent calendar rows only; never replace with zero.','candidate_definition':f"Observed at origin, {s5['history_window_months']} consecutive observed months, positive Type 1 activity in at least one of those months.",'forecast_origin':'Reporting month is a proxy; actual publication and revisions must be considered.','modelling_input':'Use calendar export for chronological features. National and observed-only files are benchmarks and descriptive views, not extra training rows.','prohibited':'Do not use future-derived cohort eligibility, same-target-month measures, missing targets, national totals or provenance identifiers as predictors.','limit':'No temporal split, feature engineering or modelling has been performed.'}
        decisions=pd.DataFrame([['Calendar verified against M04 and M05','Use final calendar for calendar-aware lagging','M07'],['Published zeros distinct from absent records','Keep reported zeros; exclude unknown targets from scoring','M07/M09'],['Origin eligibility is provisional','Apply rules at each origin, not using full-period activity','M07'],['Historical publication timing and revisions','Document as-of availability; evaluate horizon accordingly','M07/M09'],['Organisation variants and service status','Keep codes separate pending authoritative verification','M07/M09']],columns=['evidence','decision','stage'])
        ev.write_table('reports/m06_data_dictionary.csv',dictionary);ev.write_table('reports/m06_monthly_profile.csv',monthly);ev.write_table('reports/m06_national_reconciliation.csv',rec);ev.write_table('reports/m06_decisions.csv',decisions)
        for name,value in [('m06_summary.json',summary),('m06_data_contract.json',contract)]:
            file=dest/name;file.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');ev.copy_report(file.relative_to(repo).as_posix())
        ev.write_text('reports/m06_research_report.md',f"# M06 | Final dataset verification\n\nThe versioned calendar contains {len(panel):,} rows, including {len(p):,} observed provider-months and {checks['absent_rows']:,} absent records. The national dataset contains {len(n):,} monthly totals. All {len(rec):,} month-measure reconciliation comparisons matched. The final month contains {checks['latest_candidates']:,} provisional candidates among {checks['latest_observed_providers']:,} reported providers. No imputation or provider filtering was applied.\n\nThe release reproduces the pinned M05 calendar from its M04 inputs, preserves the published counts, and verifies output serialization. This establishes dataset integrity, not clinical validity or forecasting performance. The revised historical files may differ from information available at past forecast dates. Publication timing, cohort rules and chronological evaluation must be addressed in M07.\n\nSource: https://github.com/neoscar10/NHS-A-E-IDSS; M04 run {s4['run_id']}; M05 run {s5['run_id']}.\n")
        for name,fig in figures(panel,monthly,n,rec):ev.save_figure(fig,name);plt.close(fig)
        for rel in outputs:ev.record_input(rel)
        ev.finish('Dataset verification complete; modelling assumptions remain for the forecasting stage.',review_required=rc is None)
        status=json.loads((ev.path/'evidence_manifest.json').read_text(encoding='utf-8'))['status']
        return {'summary':summary,'panel':panel,'monthly':monthly,'national':n,'reconciliation':rec,'dictionary':dictionary,'decisions':decisions,'evidence_path':str(ev.path),'evidence_status':status,'output_path':str(dest)}
    except Exception as exc:
        if not ev.sealed:
            ev.write_text('reports/m06_failure.txt',f'{type(exc).__name__}: {exc}\n');ev.finish('Incomplete run. Do not use partial outputs.',review_required=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,default=Path.cwd());parser.add_argument('--m05-run-id');args=parser.parse_args();r=run_finalise(args.repo,args.m05_run_id)
    print(json.dumps({'summary':r['summary'],'evidence_status':r['evidence_status'],'evidence_path':r['evidence_path']},indent=2))
    if r['evidence_status']!='COMPLETE':raise SystemExit(2)

if __name__=='__main__':main()
