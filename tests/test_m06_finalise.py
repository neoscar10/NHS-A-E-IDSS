"""Regression tests for final dataset verification using fictional records."""
import pandas as pd
import pytest
from src.data.m05_longitudinal import prepare_panel
from src.data.m06_finalise import canonical_csv, verify_release, release_dictionary, PANEL_FIELDS, TARGET, OUTPUT_COLUMNS
from test_m05_longitudinal import inputs


def fixture():
    p,n=inputs();a,profile,m=prepare_panel(p,n)
    s={'history_window_months':12,'calendar_rows':len(a),'observed_rows':int(a.is_observed.sum()),'absent_rows':int((~a.is_observed).sum()),'reported_zero_rows':int(a.observation_state.eq('Reported zero').sum()),'candidate_origin_rows':int(a.type1_candidate.sum()),'reporting_months':len(m),'provider_codes':int(a.org_code.nunique()),'latest_candidates':int(m.iloc[-1].candidate_rows),'latest_observed_providers':int(m.iloc[-1].observed_rows),'latest_month':m.iloc[-1].period.strftime('%Y-%m')}
    return canonical_csv(a),p,n,s


def test_release_preserves_observed_rows_and_reconciles():
    a,p,n,s=fixture();panel,observed,national,_,_,rec,checks=verify_release(a,p,n,s)
    assert len(observed)==len(p) and len(national)==len(n) and len(rec)==18*len(n)
    assert rec.status.eq('MATCH').all() and checks['calendar_rows']==len(panel)

@pytest.mark.parametrize('field,value',[(TARGET,'999'),('type1_candidate','True'),('observed_last_n_months','999'),('org_name','Incorrect')])
def test_modified_calendar_rejected(field,value):
    a,p,n,s=fixture();a.loc[0,field]=value
    with pytest.raises(ValueError,match='calendar differs'):verify_release(a,p,n,s)


def test_missing_row_rejected():
    a,p,n,s=fixture()
    with pytest.raises(ValueError,match='calendar differs'):verify_release(a.iloc[:-1],p,n,s)


def test_absent_count_not_zero():
    a,p,n,s=fixture();i=a.index[a.is_observed.eq('False')][0];a.loc[i,TARGET]='0'
    with pytest.raises(ValueError,match='calendar differs'):verify_release(a,p,n,s)


def test_summary_mismatch_rejected():
    a,p,n,s=fixture();s['observed_rows']+=1
    with pytest.raises(ValueError,match='summary mismatch'):verify_release(a,p,n,s)


def test_national_mismatch_rejected():
    a,p,n,s=fixture();n.loc[0,TARGET]='999'
    with pytest.raises(ValueError,match='reconciliation failed'):verify_release(a,p,n,s)


def test_wrong_national_identity_rejected():
    a,p,n,s=fixture();n.loc[0,'org_code']='R01'
    with pytest.raises(ValueError,match='non-TOTAL'):verify_release(a,p,n,s)


def test_dictionary_full_coverage():
    assert release_dictionary().field.tolist()==OUTPUT_COLUMNS+PANEL_FIELDS
