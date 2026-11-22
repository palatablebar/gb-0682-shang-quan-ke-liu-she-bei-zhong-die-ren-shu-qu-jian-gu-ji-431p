import csv,io
from app import store
from app.modules.m7_archive.export_out import bundle,checksum
from app.workflow import load,run
from app.errors import DomainError
import pytest

def test_export_rows(state):
    rows=list(csv.reader(io.StringIO(bundle(state).lstrip('\ufeff'))));assert rows[0][0]=='记录类型' and rows[1][0]=='运行清单'
def test_export_quarantine(state):
    assert bundle(state).count('隔离')==len(state['quarantine'])
def test_checksum_stable(state):
    assert checksum(state)==state['archive']['sha256'] and len(checksum(state))==64
def test_archive_ready(state):
    assert state['archive']['ready'] is True
def test_idempotent_store(state,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    a=store.save(state['run_id'],state);b=store.save(state['run_id'],state)
    assert a['run_id']==b['run_id'] and len(store.history())==1
def test_stale_review(state,tmp_path,monkeypatch):
    # TRAP-26
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'));store.save(state['run_id'],state)
    assert store.review(state['run_id'],1,'通过')['review_version']==2
    with pytest.raises(DomainError) as e:store.review(state['run_id'],1,'退回')
    assert e.value.status==409
def test_persistent_new_connection(state,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'));store.save(state['run_id'],state)
    assert store.get(state['run_id'])['calculations']==state['calculations']

def test_gate_evidence_row_in_bundle(raw):
    s=run(raw,{'gate_total':3000})
    text=bundle(s)
    assert '闸机对证' in text and 'GATE_MATCH' in text and 'EVIDENCE' in text

def test_gate_mismatch_blocks_ready(raw):
    s=run(raw,{'gate_total':999999})
    assert s['archive']['ready'] is False and s['archive']['gate_status']=='GATE_MISMATCH'

def test_supplement_row_in_bundle(raw):
    from app.workflow import supplement
    patch='id,bucket,version,kind,left,right,count,unit,note\n02001,2026-11-16T21:00:00+08:00,1,zone,东门,,50,人,补\n'.encode('utf-8')
    s=supplement(run(raw,{}),patch)
    assert '补录' in bundle(s) and s['supplement']['base_run_id']

def test_pending_export_blocked(client):
    s=client.post('/api/runs',json={'sample':'dirty.csv','parameters':{'gate_total':999999}}).get_json()
    r=client.get('/api/archive/'+s['run_id']+'/export.csv')
    assert r.status_code==422 and r.get_json()['code']=='UNBALANCED'

def test_supplement_endpoint_and_old_batch_kept(client):
    base=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    patch='id,bucket,version,kind,left,right,count,unit,note\n03001,2026-11-16T21:00:00+08:00,1,zone,东门,,50,人,补\n03002,2026-11-16T21:00:00+08:00,1,zone,中庭,,40,人,补\n03003,2026-11-16T21:00:00+08:00,1,zone,西门,,30,人,补\n03004,2026-11-16T21:00:00+08:00,1,pair,东门,中庭,10,人,补\n03005,2026-11-16T21:00:00+08:00,1,pair,东门,西门,10,人,补\n03006,2026-11-16T21:00:00+08:00,1,pair,中庭,西门,10,人,补\n'
    r=client.post('/api/runs/'+base['run_id']+'/supplement',json={'csv':patch})
    assert r.status_code==200
    out=r.get_json()
    assert out['supplement']['affected_buckets']==['2026-11-16T13:00:00+00:00']
    # 旧批次仍可读取，记录未丢失
    assert client.get('/api/runs/'+base['run_id']).status_code==200
    # 同批重跑不新增对账版本
    again=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    assert again['run_id']==base['run_id'] and again['review_version']==base['review_version']

def test_supplement_failure_keeps_latest(client):
    base=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    # 跨桶同ID冲突：RECOMPUTE 拒绝，latest 仍是旧批次
    patch='id,bucket,version,kind,left,right,count,unit,note\n00001,2026-11-16T21:00:00+08:00,1,zone,东门,,130,人,冲突\n'
    r=client.post('/api/runs/'+base['run_id']+'/supplement',json={'csv':patch})
    assert r.status_code==422 and r.get_json()['code']=='RECOMPUTE'
    assert client.get('/api/runs').get_json()[0]['id']==base['run_id']

def test_pending_review_blocked_but_return_allowed(client):
    s=client.post('/api/runs',json={'sample':'dirty.csv','parameters':{'gate_total':999999}}).get_json()
    blocked=client.post('/api/runs/'+s['run_id']+'/review',json={'version':1,'decision':'通过'})
    assert blocked.status_code==422 and blocked.get_json()['code']=='REVIEW'
    ok=client.post('/api/runs/'+s['run_id']+'/review',json={'version':1,'decision':'退回'})
    assert ok.status_code==200 and ok.get_json()['decision']=='退回'

def test_pages_render_with_gate_and_supplement(client):
    client.post('/api/runs',json={'sample':'dirty.csv','parameters':{'gate_total':3000}})
    page6=client.get('/m6_reconcile').data.decode()
    assert '闸机日结总量' in page6 and '佐证一致' in page6 and '小时补录' in page6
    page7=client.get('/m7_archive').data.decode()
    assert '闸机对证' in page7 and '可封存' in page7
