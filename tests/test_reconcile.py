from copy import deepcopy
from app.modules.m6_reconcile.compare import balance,gate_total,gate_check
from app.workflow import run,load
from app.errors import DomainError
import pytest

def test_count_conservation(state):
    assert state['reconcile']['balanced'] is True
def test_input_total(state):
    r=state['reconcile'];assert r['input']==r['accepted']+r['isolated']+r['blank']+r['headers']+r['duplicates']
def test_quarantine_visible(state):
    assert state['reconcile']['isolated']>=4
def test_broken_count_detected(state):
    s=deepcopy(state);s['input_count']+=1;b=balance(s)
    assert b['balanced'] is False and b['pending'] is True
def test_clean_count():
    s=run(load('clean.csv'),{});assert s['reconcile']['balanced'] and s['reconcile']['isolated']==0
def test_business_has_totals(state):
    assert state['reconcile']['business'] and 'total' in state['reconcile']['business']
def test_no_evidence_lost(state):
    assert all(r['line']>=2 and r['code'] for r in state['quarantine'])

# --- 裁决：闸机总量是佐证，不是正式约束 ---
def test_no_gate_keeps_interval_only(raw):
    s=run(raw,{})['reconcile']
    assert s['gate']['provided'] is False and s['gate']['status']=='WITHOUT_GATE'
    assert s['pending'] is False and s['gate']['adjudication']=='EVIDENCE'

def test_gate_inside_interval_is_evidence_not_constraint(raw):
    s=run(raw,{'gate_total':3000})
    g=s['reconcile']['gate']
    # 落在区间内：只标记佐证一致，正式区间不被收窄成单点
    assert g['status']=='GATE_MATCH' and g['deviation']==0
    assert s['business']['total']<3000<s['business']['upper_total']
    assert s['reconcile']['pending'] is False and s['archive']['ready'] is True

def test_gate_equals_bound_is_match(raw):
    s=run(raw,{'gate_total':run(raw,{})['business']['total']})
    assert s['reconcile']['gate']['status']=='GATE_MATCH'

def test_gate_outside_interval_pending_not_forced(raw):
    s=run(raw,{'gate_total':999999})
    g=s['reconcile']['gate']
    # 越出区间：总量与区间同时保留，转待核对，绝不把总量写成正式结果
    assert g['status']=='GATE_MISMATCH' and g['deviation']>0
    assert s['reconcile']['pending'] is True and s['archive']['ready'] is False
    assert s['business']['upper_total']<999999

def test_gate_below_interval_pending(raw):
    s=run(raw,{'gate_total':1})
    assert s['reconcile']['gate']['status']=='GATE_MISMATCH'
    assert s['reconcile']['pending'] is True

def test_invalid_gate_total_rejected(raw):
    for bad in ('abc','1.5','-3',True,[3]):
        with pytest.raises(DomainError) as e:run(raw,{'gate_total':bad})
        assert e.value.code=='GATE'

def test_gate_total_parser():
    assert gate_total({'gate_total':'123'})==123 and gate_total({}) is None
    assert gate_total({'gate_total':0})==0

def test_gate_check_does_not_mutate_business(raw):
    before=run(raw,{});after=run(raw,{'gate_total':999999})
    assert before['business']==after['business']
    assert before['calculations']==after['calculations']

def test_gate_block_shape(raw):
    g=gate_check(run(raw,{})['business'],{'gate_total':3000})
    assert set(g)>={'provided','gate_total','lower_total','upper_total','status','deviation','adjudication'}
