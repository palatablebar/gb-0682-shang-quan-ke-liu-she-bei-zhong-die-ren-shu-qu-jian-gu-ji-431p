import pytest
from app.workflow import run,load,supplement
from app import store
from app.errors import DomainError

HEADER='id,bucket,version,kind,left,right,count,unit,note\n'

def patch(*lines):
    return (HEADER+'\n'.join(lines)+'\n').encode('utf-8')

def test_supplement_only_recomputes_affected_hour(raw):
    base=run(raw,{})
    p=patch('01001,2026-11-16T21:00:00+08:00,1,zone,东门,,50,人,补',
            '01002,2026-11-16T21:00:00+08:00,1,zone,中庭,,40,人,补',
            '01003,2026-11-16T21:00:00+08:00,1,zone,西门,,30,人,补',
            '01004,2026-11-16T21:00:00+08:00,1,pair,东门,中庭,10,人,补',
            '01005,2026-11-16T21:00:00+08:00,1,pair,东门,西门,10,人,补',
            '01006,2026-11-16T21:00:00+08:00,1,pair,中庭,西门,10,人,补')
    out=supplement(base,p)
    # 21:00 (+08:00) 归整到 13:00 UTC
    affected='2026-11-16T13:00:00+00:00'
    assert out['supplement']['affected_buckets']==[affected]
    before={c['id']:c for c in base['calculations']}
    after={c['id']:c for c in out['calculations']}
    # 原有小时桶结果一个都不变
    assert all(before[k]==after[k] for k in before)
    # 新增的只是补录小时桶
    assert set(after)-set(before)=={affected}
    # 输入计数为含表头的全部逻辑记录增量
    assert out['input_count']==base['input_count']+7

def test_supplement_new_version_within_same_hour(raw):
    base=run(raw,{})
    first=base['calculations'][0];bucket=first['id']
    p=patch('00001,'+bucket.replace('+00:00','+00:00')+',2,zone,东门,,130,人,补录高版本')
    out=supplement(base,p)
    new_calc={c['id']:c for c in out['calculations']}[bucket]
    others=[c for c in out['calculations'] if c['id']!=bucket]
    base_others=[c for c in base['calculations'] if c['id']!=bucket]
    assert others==base_others  # 只重算对应小时
    assert new_calc!=first
    assert out['supplement']['base_run_id']==base['run_id']

def test_supplement_rejects_change_outside_affected_hours(raw):
    base=run(raw,{})
    # 复用原批次ID 00001（原属01:00 UTC桶），补录到另一小时：
    # 同(id,version)跨桶冲突会隔离两个桶，而补丁只声明影响新桶，旧桶变化越界 -> 拒绝
    p=patch('00001,2026-11-16T21:00:00+08:00,1,zone,东门,,130,人,跨桶冲突')
    with pytest.raises(DomainError) as e:supplement(base,p)
    assert e.value.code=='RECOMPUTE'
    # 失败后原批次状态对象不被修改
    assert base['input_count']==run(raw,{})['input_count']

def test_supplement_bad_header_rejected(raw):
    base=run(raw,{})
    with pytest.raises(DomainError) as e:supplement(base,b'id,bucket\nx,y\n')
    assert e.value.code=='HEADER'

def test_supplement_empty_rejected(raw):
    base=run(raw,{})
    with pytest.raises(DomainError) as e:supplement(base,b'   \n')
    assert e.value.code in ('BLANK_FILE','HEADER')

def test_supplement_failure_keeps_old_batch(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    original=run(raw,{});base_id=original['run_id']
    store.save(base_id,original)
    # replace_latest 记录守恒校验失败时抛错，旧批次原样保留
    bad=deepcopy_via_json(original);bad['input_count']=original['input_count']-1;bad['run_id']='newbad'
    with pytest.raises(DomainError) as e:store.replace_latest(bad)
    assert e.value.code=='SWITCH'
    again=store.get(base_id)
    assert again['run_id']==base_id and again['input_count']==original['input_count']
    assert store.history()[0]['id']==base_id

def test_supplement_switch_keeps_all_evidence(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    original=run(raw,{});base=store.save(original['run_id'],original)
    p=patch('01001,2026-11-16T21:00:00+08:00,1,zone,东门,,50,人,补',
            '01002,2026-11-16T21:00:00+08:00,1,zone,中庭,,40,人,补',
            '01003,2026-11-16T21:00:00+08:00,1,zone,西门,,30,人,补',
            '01004,2026-11-16T21:00:00+08:00,1,pair,东门,中庭,10,人,补',
            '01005,2026-11-16T21:00:00+08:00,1,pair,东门,西门,10,人,补',
            '01006,2026-11-16T21:00:00+08:00,1,pair,中庭,西门,10,人,补')
    new_state=supplement(base,p)
    switched=store.replace_latest(new_state)
    assert store.get(base['run_id'])['input_count']==base['input_count']  # 旧批次未被覆盖删除
    assert switched['input_count']==base['input_count']+7
    # 隔离证据与原计算桶都还在
    assert len(switched['quarantine'])>=len(base['quarantine'])
    assert {c['id'] for c in base['calculations']}<={c['id'] for c in switched['calculations']}

def test_same_rerun_never_creates_version(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    s=run(raw,{})
    store.save(s['run_id'],s);store.review(s['run_id'],1,'通过')
    again=run(raw,{})  # 同输入同参数同规则：同批重跑
    got=store.save(again['run_id'],again)
    assert got['review_version']==2 and got['decision']=='通过'
    assert len(store.history())==1

def test_pending_blocks_review_and_export(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    s=run(raw,{'gate_total':999999})
    saved=store.save(s['run_id'],s)
    assert saved['reconcile']['pending'] is True
    with pytest.raises(DomainError) as e:store.review(s['run_id'],1,'通过')
    assert e.value.code=='REVIEW'
    # 退回仍然允许（运营可打回修正）
    assert store.review(s['run_id'],1,'退回')['decision']=='退回'

def deepcopy_via_json(obj):
    import json
    return json.loads(json.dumps(obj,ensure_ascii=False))
