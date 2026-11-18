"""Build an auditable provider-month calendar and time-aware forecasting candidates."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import importlib.util
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from src.data.data_preprocessing import OUTPUT_COLUMNS, MEASURE_NAMES, TARGET
from src.utils.evidence_exporter import EvidenceRun, digest

STATUSES = ['Candidate', 'No recent positive activity', 'Insufficient consecutive history', 'No reported record']


def read_m04(repo, run_id=None):
    root = repo / 'data/processed/m04'
    if run_id is None:
        runs = sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r'\d{8}T\d{6}Z_[0-9a-f]+', p.name))
        if not runs:
            raise FileNotFoundError('No M04 run found')
        run_id = runs[-1]
    if not re.fullmatch(r'\d{8}T\d{6}Z_[0-9a-f]+', run_id):
        raise ValueError('Invalid M04 run ID')
    folder = root / run_id
    paths = [folder/'m04_summary.json', repo/'docs/evidence/M04_Preprocessing'/run_id/'evidence_manifest.json', folder/'ae_provider_monthly.csv', folder/'ae_national_monthly.csv']
    summary, manifest = [json.loads(p.read_text(encoding='utf-8')) for p in paths[:2]]
    if summary['status'] != 'PASS_STANDARDISATION' or manifest['status'] != 'COMPLETE' or summary['run_id'] != run_id or manifest['run_id'] != run_id:
        raise ValueError('M04 run is not complete; select a verified M04 run')
    for p in [paths[0], *paths[2:]]:
        rel = p.relative_to(repo).as_posix()
        actual = digest(p)
        if manifest['inputs'][rel]['sha256'] != actual or (p != paths[0] and summary['outputs'][rel]['sha256'] != actual):
            raise ValueError(f'M04 fingerprint mismatch: {rel}')
    provider = pd.read_csv(paths[2], dtype='string', keep_default_na=False)
    national = pd.read_csv(paths[3], dtype='string', keep_default_na=False)
    if len(provider) != summary['provider_rows'] or len(national) != summary['national_rows']:
        raise ValueError('M04 record counts do not match summary')
    return provider, national, summary, paths


def typed(frame):
    if list(frame.columns) != OUTPUT_COLUMNS:
        raise ValueError('Unexpected M04 schema')
    f = frame.copy()
    f['period'] = pd.to_datetime(f.period, format='%Y-%m-%d', errors='raise')
    if f.period.isna().any() or not f.period.dt.day.eq(1).all() or not f.period.dt.strftime('%Y-%m').eq(f.source_month).all():
        raise ValueError('Invalid reporting month')
    for col in MEASURE_NAMES:
        s = f[col].astype('string')
        if not s.str.fullmatch(r'[0-9]+').fillna(False).all():
            raise ValueError(f'Invalid count: {col}')
        f[col] = s.map(int).astype('Int64')
    return f


def prepare_panel(provider, national, window=12):
    """Create calendar rows from first observed month; use only history through each origin."""
    if not isinstance(window,int) or window < 1:
        raise ValueError('History window must be positive')
    p,n = typed(provider),typed(national)
    if p.empty or n.empty or p.org_code.isna().any() or p.org_code.str.strip().eq('').any() or p.org_code.str.upper().eq('TOTAL').any():
        raise ValueError('Expected valid provider records, excluding national totals')
    if p.duplicated(['period','org_code']).any():
        raise ValueError('Duplicate provider-month key')
    if n.period.duplicated().any():
        raise ValueError('Duplicate national reporting month')
    months = pd.date_range(n.period.min(),n.period.max(),freq='MS')
    if set(months) != set(n.period) or set(p.period) != set(months):
        raise ValueError('Incomplete global reporting calendar')
    parts=[]; profiles=[]
    for code,g in p.groupby('org_code',sort=True):
        g=g.sort_values('period').set_index('period')
        first,last=g.index.min(),g.index.max()
        calendar=pd.date_range(first,months[-1],freq='MS',name='period')
        block=g.reindex(calendar)
        observed=pd.Series(calendar.isin(g.index),index=calendar)
        valid=block[TARGET].notna()
        if not observed.eq(valid).all():
            raise ValueError('Observed record missing Type 1 count')
        positive=block[TARGET].gt(0).fillna(False)
        block['org_code']=code
        block['is_observed']=observed
        block['observation_state']='Absent record'
        block.loc[observed & ~positive,'observation_state']='Reported zero'
        block.loc[observed & positive,'observation_state']='Reported positive'
        block['observed_last_n_months']=observed.astype(int).rolling(window,min_periods=1).sum().astype('int64')
        block['positive_last_n_months']=positive.astype(int).rolling(window,min_periods=1).sum().astype('int64')
        block['history_ready']=block.observed_last_n_months.eq(window)
        block['type1_candidate']=observed & block.history_ready & block.positive_last_n_months.gt(0)
        block['candidate_status']=STATUSES[2]
        block.loc[~observed,'candidate_status']=STATUSES[3]
        block.loc[observed & block.history_ready & block.positive_last_n_months.eq(0),'candidate_status']=STATUSES[1]
        block.loc[block.type1_candidate,'candidate_status']=STATUSES[0]
        block['history_window_months']=window
        # No forward filling of organisation attributes or numeric observations.
        parts.append(block.reset_index())
        names=g.org_name.dropna().astype(str).unique(); parents=g.parent_org.dropna().astype(str).unique()
        inside=(last.year-first.year)*12+last.month-first.month+1
        profiles.append({'org_code':code,'first_observed_month':first.strftime('%Y-%m'),'last_observed_month':last.strftime('%Y-%m'),
                         'observed_months':len(g),'missing_within_observed_span':inside-len(g),'absent_after_last_observation':len(calendar)-inside,
                         'zero_type1_observations':int(g[TARGET].eq(0).sum()),'positive_type1_observations':int(g[TARGET].gt(0).sum()),
                         'distinct_recorded_names':len(names),'distinct_recorded_parent_groups':len(parents),
                         'recorded_names':' | '.join(sorted(names)),'recorded_parent_groups':' | '.join(sorted(parents))})
    panel=pd.concat(parts,ignore_index=True).sort_values(['period','org_code']).reset_index(drop=True)
    panel=panel[[*OUTPUT_COLUMNS,'is_observed','observation_state','observed_last_n_months','positive_last_n_months','history_ready','type1_candidate','candidate_status','history_window_months']]
    observed=panel.loc[panel.is_observed,OUTPUT_COLUMNS].sort_values(['period','org_code']).reset_index(drop=True)
    original=p.sort_values(['period','org_code']).reset_index(drop=True)
    pd.testing.assert_frame_equal(observed,original,check_dtype=False)
    assert panel.loc[~panel.is_observed,MEASURE_NAMES].isna().all().all()
    assert not panel.duplicated(['period','org_code']).any()
    profile=pd.DataFrame(profiles)
    monthly=panel.groupby('period').agg(calendar_rows=('org_code','size'),observed_rows=('is_observed','sum'),candidate_rows=('type1_candidate','sum')).reset_index()
    monthly['absent_rows']=monthly.calendar_rows-monthly.observed_rows
    category=panel.groupby(['period','candidate_status']).size().unstack(fill_value=0).reindex(columns=STATUSES,fill_value=0).reset_index()
    monthly=monthly.merge(category,on='period',validate='one_to_one')
    return panel,profile,monthly


def figures(panel,profile,monthly,window):
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    ax.plot(monthly.period,monthly.calendar_rows,label='Previously observed codes, calendar rows',color='#64748b',linestyle='--')
    ax.plot(monthly.period,monthly.observed_rows,label='Reported provider records',color='#22658a',linewidth=2)
    ax.fill_between(monthly.period,monthly.observed_rows,monthly.calendar_rows,color='#d18b3f',alpha=.22,label='Absent records, not zero activity')
    ax.set(title='Reporting coverage varies after providers first appear',xlabel='Reporting month',ylabel='Provider codes');ax.grid(axis='y',alpha=.2);ax.yaxis.set_major_locator(MaxNLocator(integer=True));ax.legend(loc='upper center',bbox_to_anchor=(.5,-.19),frameon=False,fontsize=8,ncol=2)
    yield '01_reporting_coverage.png',fig
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    colors=['#25877d','#d18b3f','#8c9cb1','#d5d9e0']
    ax.stackplot(monthly.period,*[monthly[k] for k in STATUSES],labels=STATUSES,colors=colors,alpha=.9)
    ax.set(title=f'Forecast-origin candidate population: {window}-month history window',xlabel='Reporting month (latest available observation)',ylabel='Provider codes');ax.legend(loc='upper center',bbox_to_anchor=(.5,-.19),ncol=2,fontsize=9,frameon=False);ax.yaxis.set_major_locator(MaxNLocator(integer=True));ax.grid(axis='y',alpha=.15)
    yield '02_time_aware_candidates.png',fig
    fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
    shortlist=profile.loc[profile.missing_within_observed_span.gt(0)].sort_values(['missing_within_observed_span','org_code'],ascending=[False,True]).head(12)
    if shortlist.empty:
        ax.text(.5,.5,'No internal reporting gaps detected',ha='center',va='center',transform=ax.transAxes);ax.set_axis_off()
    else:
        ax.barh(shortlist.org_code,shortlist.missing_within_observed_span,color='#d18b3f');ax.invert_yaxis();ax.set_xlabel('Absent months within first and last observed month');ax.grid(axis='x',alpha=.2);ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlim(0,max(1,shortlist.missing_within_observed_span.max())*1.2)
        for i,v in enumerate(shortlist.missing_within_observed_span):ax.text(v,i,f' {v}',va='center')
    ax.set_title('Internal reporting gaps: providers requiring continuity review',loc='left',fontweight='bold')
    yield '03_provider_gap_review.png',fig


def run_longitudinal(repo, m04_run_id=None, window=12, run_tests=True, notebook=False):
    repo=Path(repo).resolve()
    evidence=EvidenceRun(repo,'M05','Prepare provider-month continuity and time-aware Type 1 forecasting candidates.')
    try:
        for rel in ('src/data/longitudinal_preparation.py','src/data/data_preprocessing.py','src/utils/evidence_exporter.py'):
            evidence.record_input(rel)
        if notebook:evidence.record_input('notebooks/04_longitudinal_preparation.ipynb')
        p,n,m04,paths=read_m04(repo,m04_run_id)
        for path in paths:evidence.record_input(path.relative_to(repo).as_posix())
        panel,profile,monthly=prepare_panel(p,n,window)
        rc=evidence.run_tests('tests/test_longitudinal_preparation.py') if run_tests else None
        if rc not in (None,0):raise RuntimeError('M05 regression tests failed')
        dest=repo/'data/processed/m05'/evidence.run_id
        if dest.resolve()!=dest:raise ValueError('Invalid output location')
        dest.mkdir(parents=True,exist_ok=False)
        outputs={}
        parquet=importlib.util.find_spec('pyarrow') is not None
        for name,frame in [('ae_provider_calendar',panel)]:
            path=dest/f'{name}.csv';frame.to_csv(path,index=False,date_format='%Y-%m-%d');outputs[path.relative_to(repo).as_posix()]={'rows':len(frame),'sha256':digest(path)}
            if parquet:
                path=dest/f'{name}.parquet';frame.to_parquet(path,index=False,engine='pyarrow');outputs[path.relative_to(repo).as_posix()]={'rows':len(frame),'sha256':digest(path)}
        latest=monthly.iloc[-1]; absent=int((~panel.is_observed).sum()); gaps=int(profile.missing_within_observed_span.sum()); trailing=int(profile.absent_after_last_observation.sum())
        assert absent==gaps+trailing
        s={'status':'PASS_LONGITUDINAL_PREPARATION','run_id':evidence.run_id,'m04_run_id':m04['run_id'],'history_window_months':window,'reporting_months':len(monthly),'provider_codes':len(profile),'observed_rows':int(panel.is_observed.sum()),'calendar_rows':len(panel),'absent_rows':absent,'internal_gap_rows':gaps,'absent_after_last_observation_rows':trailing,'providers_with_internal_gaps':int(profile.missing_within_observed_span.gt(0).sum()),'providers_with_name_variants':int(profile.distinct_recorded_names.gt(1).sum()),'providers_with_parent_variants':int(profile.distinct_recorded_parent_groups.gt(1).sum()),'reported_zero_rows':int(panel.observation_state.eq('Reported zero').sum()),'latest_month':latest.period.strftime('%Y-%m'),'latest_candidates':int(latest.candidate_rows),'latest_observed_providers':int(latest.observed_rows),'candidate_origin_rows':int(panel.type1_candidate.sum()),'test_exit_code':rc,'outputs':outputs,'parquet_status':'exported' if parquet else 'CSV only; PyArrow not installed'}
        decisions=pd.DataFrame([
            ['Absent provider-month','Keep measures null; no imputation or inferred closure','Implemented'],
            ['Reported zeros','Retain exactly as published','Implemented'],
            ['Name and parent variants','Flag for source-based identity review; no merging','Review required where flagged'],
            ['Candidate eligibility','Observed at origin, full history window, at least one reported positive Type 1 value in window','Provisional operational rule'],
            ['Candidate status','Use only observations at or before origin; never filter by future outcome','Implemented'],
            ['Publication timing','Confirm availability at each forecast origin before feature engineering','M07'],
            ['Actual Type 1 service status','Validate against authoritative organisation/service evidence if available','Open limitation'],
            ['Outliers','Retain observed values; inspect M03 change candidates and source context','Review required where flagged'],
        ],columns=['finding','decision','status'])
        evidence.write_table('reports/m05_provider_continuity.csv',profile)
        evidence.write_table('reports/m05_monthly_eligibility.csv',monthly)
        evidence.write_table('reports/m05_decisions.csv',decisions)
        evidence.write_text('reports/m05_summary.json',json.dumps(s,indent=2)+'\n')
        evidence.write_text('reports/m05_research_report.md',f"""# M05 | Longitudinal preparation

## Results
The calendar retains {s['observed_rows']:,} observed provider-months and identifies {absent:,} absent records after providers first appear. Of these, {gaps:,} fall within observed reporting spans and {trailing:,} occur after last observation. No absent counts were set to zero. There are {s['providers_with_name_variants']} codes with recorded name variants and {s['providers_with_parent_variants']} with parent variants. The latest reporting month ({s['latest_month']}) contains {s['latest_candidates']} provisional candidates out of {s['latest_observed_providers']} reported providers.

## Method and interpretation
The calendar starts at the first observed month of each code. The candidate rule requires an observed origin and {window} consecutive reported months through that origin, including at least one positive Type 1 observation in the window. It does not use future observations. Recorded activity is a proxy, not verification of service type. Reporting absence is not evidence of closure. Name changes or parent changes are not evidence of mergers; source verification remains necessary. All observations and advisories remain available for modelling design. Publication availability must be addressed before training and evaluation. No forecasting models have been fitted.

Source: https://github.com/neoscar10/NHS-A-E-IDSS; M04 run {m04['run_id']}.
""")
        for name,fig in figures(panel,profile,monthly,window):evidence.save_figure(fig,name);plt.close(fig)
        path=dest/'m05_summary.json';path.write_text(json.dumps(s,indent=2)+'\n',encoding='utf-8')
        for rel in [*outputs,path.relative_to(repo).as_posix()]:evidence.record_input(rel)
        evidence.finish('Calendar preparation complete; cohort assumptions and identity advisories remain subject to review.',review_required=rc is None)
        manifest=json.loads((evidence.path/'evidence_manifest.json').read_text(encoding='utf-8'))
        return {'summary':s,'panel':panel,'profile':profile,'monthly':monthly,'decisions':decisions,'evidence_path':str(evidence.path),'evidence_status':manifest['status']}
    except Exception as exc:
        if not evidence.sealed:
            evidence.write_text('reports/m05_failure.txt',f'{type(exc).__name__}: {exc}\n');evidence.finish('Incomplete run. Do not use partial outputs.',review_required=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd());parser.add_argument('--m04-run-id');parser.add_argument('--window',type=int,default=12)
    args=parser.parse_args();r=run_longitudinal(args.repo,args.m04_run_id,args.window)
    print(json.dumps({'summary':r['summary'],'evidence_status':r['evidence_status'],'evidence_path':r['evidence_path']},indent=2))
    if r['evidence_status']!='COMPLETE':raise SystemExit(2)

if __name__=='__main__':main()
