import pandas as pd
import pytest
from src.data.data_preprocessing import OUTPUT_COLUMNS, MEASURE_NAMES, TARGET
from src.data.longitudinal_preparation import prepare_panel


def inputs(months=15):
    rows=[]; totals=[]
    for i,m in enumerate(pd.date_range('2022-01-01',periods=months,freq='MS')):
        vals=[('R01',10),('R02',0)]
        if i>=3 and i!=9: vals.append(('R03',5))
        if i<=6: vals.append(('R04',1))
        for code,value in vals+[('TOTAL',sum(v for _,v in vals))]:
            r=dict.fromkeys(OUTPUT_COLUMNS,'');r.update(dict.fromkeys(MEASURE_NAMES,'0'))
            r.update(period=m.strftime('%Y-%m-%d'),source_month=m.strftime('%Y-%m'),org_code=code,org_name=code+' name',parent_org='region',source_file='fixture.csv',source_sha256='a'*64,source_record_number=str(len(rows)+1))
            r[TARGET]=str(value);(totals if code=='TOTAL' else rows).append(r)
    return pd.DataFrame(rows,columns=OUTPUT_COLUMNS).astype('string'),pd.DataFrame(totals,columns=OUTPUT_COLUMNS).astype('string')


def test_observed_rows_conserved():
    p,n=inputs();panel,_,_=prepare_panel(p,n);assert panel.is_observed.sum()==len(p)
    assert panel.loc[panel.is_observed,TARGET].sum()==p[TARGET].astype(int).sum()


def test_missing_not_zero():
    p,n=inputs();panel,_,_=prepare_panel(p,n);absent=panel.loc[~panel.is_observed]
    assert len(absent)>0 and absent[MEASURE_NAMES].isna().all().all()
    assert panel.loc[panel.org_code.eq('R02'),TARGET].eq(0).all()


def test_calendar_starts_at_first_observation():
    p,n=inputs();panel,_,_=prepare_panel(p,n);assert panel.loc[panel.org_code.eq('R03'),'period'].min()==pd.Timestamp('2022-04-01')


def test_no_assumed_exit():
    p,n=inputs();panel,profile,_=prepare_panel(p,n)
    assert profile.set_index('org_code').loc['R04','absent_after_last_observation']==8
    assert not panel.loc[panel.org_code.eq('R04') & ~panel.is_observed,'type1_candidate'].any()


def test_candidate_requires_complete_history():
    p,n=inputs();panel,_,_=prepare_panel(p,n);r=panel.loc[panel.org_code.eq('R01')]
    assert r.type1_candidate.tolist()==[False]*11+[True]*4


def test_all_zero_not_candidate():
    p,n=inputs();panel,_,_=prepare_panel(p,n);assert not panel.loc[panel.org_code.eq('R02'),'type1_candidate'].any()


def test_internal_gap_breaks_contiguous_history():
    p,n=inputs();panel,profile,_=prepare_panel(p,n,window=3)
    r=panel.loc[panel.org_code.eq('R03')].set_index('period')
    assert not r.loc[pd.Timestamp('2022-11-01'),'history_ready']
    assert r.loc[pd.Timestamp('2023-01-01'),'history_ready']
    assert profile.set_index('org_code').loc['R03','missing_within_observed_span']==1


def test_future_changes_do_not_change_past_eligibility():
    p,n=inputs();a,_,_=prepare_panel(p,n,window=3)
    p.loc[p.source_month.ge('2023-01') & p.org_code.eq('R02'),TARGET]='20'
    b,_,_=prepare_panel(p,n,window=3)
    columns=['period','org_code','type1_candidate','history_ready','positive_last_n_months']
    pd.testing.assert_frame_equal(a.loc[a.period.lt('2023-01-01'),columns],b.loc[b.period.lt('2023-01-01'),columns])


def test_positive_history_allows_zero_at_origin():
    p,n=inputs();p.loc[p.source_month.eq('2023-03') & p.org_code.eq('R01'),TARGET]='0';panel,_,_=prepare_panel(p,n)
    assert panel.loc[panel.org_code.eq('R01') & panel.period.eq('2023-03-01'),'type1_candidate'].item()


def test_name_variants_preserved():
    p,n=inputs();p.loc[p.source_month.eq('2023-03') & p.org_code.eq('R01'),'org_name']='new name';panel,profile,_=prepare_panel(p,n)
    assert profile.set_index('org_code').loc['R01','distinct_recorded_names']==2
    assert panel.loc[panel.org_code.eq('R01'),'org_name'].nunique()==2


def test_duplicate_key_rejected():
    p,n=inputs();p=pd.concat([p,p.iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError,match='Duplicate'):prepare_panel(p,n)


def test_global_calendar_gap_rejected():
    p,n=inputs();p=p[p.source_month.ne('2022-05')];n=n[n.source_month.ne('2022-05')]
    with pytest.raises(ValueError,match='calendar'):prepare_panel(p,n)


def test_monthly_statuses_partition():
    p,n=inputs();_,_,m=prepare_panel(p,n)
    from src.data.longitudinal_preparation import STATUSES
    assert m[STATUSES].sum(axis=1).eq(m.calendar_rows).all()
