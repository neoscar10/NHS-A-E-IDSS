"""M04 regression tests using fictional records only."""
from pathlib import Path
import pandas as pd
import pytest
from src.data.data_ingestion import EXPECTED_COLUMNS
from src.data.data_validation import MEASURES, PROVENANCE
from src.data.data_preprocessing import standardise, conservation, data_dictionary, MEASURE_NAMES, OUTPUT_COLUMNS


def fixture():
    rows=[]
    for code,name,count,i in [(' r01 ',' Hospital A ',10,1),('R02','Clinic B',0,2),(' Total ',' Total ',10,3)]:
        r=dict.fromkeys(MEASURES,'0')
        r.update({'Period':'Total' if i==3 else 'MSitAE-SEPTEMBER-2026','Org Code':code,'Org name':name,
                  'Parent Org':' Region ',MEASURES[0]:str(count),'source_month':'2026-09',
                  'source_file':'data/raw/2026/September-2026-fixture.csv','source_sha256':'a'*64,'source_record_number':str(i)})
        rows.append(r)
    return pd.DataFrame(rows,columns=EXPECTED_COLUMNS+PROVENANCE).astype('string')


def test_row_conservation_and_grain():
    d=fixture();p,n,_=standardise(d)
    assert len(p)==2 and len(n)==1 and len(p)+len(n)==len(d)
    assert list(p.columns)==OUTPUT_COLUMNS and p['period'].iloc[0]==pd.Timestamp('2026-09-01')
    assert set(p.org_code)=={'R01','R02'} and set(n.org_code)=={'TOTAL'}


def test_zero_preserved_and_counts_typed():
    p,n,_=standardise(fixture())
    assert p.loc[p.org_code.eq('R02'),'type1_attendances'].iloc[0]==0
    assert all(str(p[c].dtype)=='int64' for c in MEASURE_NAMES)


def test_original_unchanged_and_provenance():
    d=fixture();before=d.copy(deep=True);p,n,_=standardise(d)
    pd.testing.assert_frame_equal(d,before)
    assert p.loc[p.org_code.eq('R01'),'org_name'].iloc[0]=='Hospital A'
    assert p.source_sha256.iloc[0]=='a'*64 and p.source_period.iloc[0]=='MSitAE-SEPTEMBER-2026'


def test_conservation_all_18_measures():
    d=fixture();p,n,_=standardise(d)
    assert conservation(d,p,n).status.eq('MATCH').sum()==18


@pytest.mark.parametrize('bad',['','-1','1.5','not reported','9223372036854775808'])
def test_invalid_counts_fail(bad):
    d=fixture();d.loc[0,MEASURES[0]]=bad
    with pytest.raises(ValueError,match='count|Count'): standardise(d)


def test_duplicate_normalised_code_fails():
    d=fixture();d.loc[1,'Org Code']='R01 '
    with pytest.raises(ValueError,match='Duplicate'): standardise(d)


def test_mismatched_total_fails():
    d=fixture();d.loc[2,MEASURES[0]]='11'
    with pytest.raises(ValueError,match='National total mismatch'): standardise(d)


def test_absent_total_fails():
    with pytest.raises(ValueError,match='national'): standardise(fixture().iloc[:2])


def test_period_mismatch_fails():
    d=fixture();d.loc[0,'Period']='MSitAE-AUGUST-2026'
    with pytest.raises(ValueError,match='period mismatch'): standardise(d)


def test_dictionary_complete():
    assert data_dictionary().field.tolist()==OUTPUT_COLUMNS


def test_no_imputation_or_panel_expansion():
    d=fixture(); other=fixture();other['source_month']='2026-11';other['Period']='MSitAE-NOVEMBER-2026';other.loc[2,'Period']='Total'
    p,n,_=standardise(pd.concat([d,other],ignore_index=True))
    assert len(p)==4 and len(n)==2 and pd.Timestamp('2026-10-01') not in p.period.tolist()


def test_columns_must_match_contract():
    with pytest.raises(ValueError,match='schema'): standardise(fixture().drop(columns=['source_month']))
