import time,importlib,json,base64,csv,io
from pathlib import Path
from app.config import MODULES
from app.errors import DomainError
from app.manifest import identity,manifest
from app.modules.m1_ingest.decode import decode

def load(sample):
    if sample not in ('dirty.csv','clean.csv','legacy.csv'):raise DomainError('SAMPLE','样例名称无效')
    return (Path(__file__).resolve().parents[1]/'sample_data'/sample).read_bytes()

def _finalize(state,content,params,elapsed):
    # Decimal values are serialized as strings before any storage or response.
    state=json.loads(json.dumps(state,default=str,ensure_ascii=False))
    state['run_id']=identity(content,params);state['manifest']=manifest(content,params,elapsed)
    state['source_b64']=base64.b64encode(content).decode('ascii')
    if state.get('reconcile') is not None and 'archive' in state:
        from app.modules.m7_archive.export_out import checksum
        state['archive']['sha256']=checksum(state)
    return state

def run(content,parameters=None,stage=7):
    if len(content)>2_000_000:raise DomainError('SIZE','文件超过2MB',413)
    params=parameters or {}
    if not isinstance(params,dict):raise DomainError('PARAMETERS','参数必须是对象')
    start=time.monotonic();state=None
    for n,entry in enumerate(MODULES,1):
        if n>stage:break
        fn=importlib.import_module('app.modules.'+entry[0]+'.service').execute
        state=fn(content,params) if n==1 else fn(state)
    return _finalize(state,content,params,time.monotonic()-start)

def _merge_content(base_content,patch_content):
    """拼接待采信CSV：保留原字节行序，补录行接在其后并顺延逻辑行号。"""
    text,_=decode(patch_content)
    if not text or not text.strip():raise DomainError('BLANK_FILE','补录内容为空')
    reader=csv.reader(io.StringIO(text,newline=''))
    try:patch_header=next(reader)
    except (StopIteration,csv.Error):raise DomainError('HEADER','无法读取补录表头')
    base_text,encoding=decode(base_content)
    base_reader=csv.reader(io.StringIO(base_text,newline=''))
    try:base_header=next(base_reader)
    except (StopIteration,csv.Error):raise DomainError('HEADER','原批次缺少表头')
    norm=lambda rows:[s.strip().lstrip('\ufeff') for s in rows]
    if norm(patch_header)!=norm(base_header):
        raise DomainError('HEADER','补录表头必须与原批次一致')
    # decode() 的 utf-8-sig 仅用于剥离BOM，重建文本时按普通utf-8解码原字节
    base_lines=base_content.decode('gb18030' if encoding=='gb18030' else 'utf-8').splitlines()
    merged='\n'.join(base_lines+text.splitlines())+'\n'
    return merged.encode('utf-8'),len(base_lines)

def _affected_buckets(patch_content):
    """补录行经时区归整后落入的UTC小时桶；只有这些桶允许改变计算结果。"""
    from app.modules.m2_mapping.coerce import instant
    text,_=decode(patch_content)
    reader=csv.DictReader(io.StringIO(text,newline=''))
    buckets=set()
    for row in reader:
        raw=(row.get('bucket') or '').strip()
        if not raw:continue
        try:
            iso=instant(raw)
            buckets.add(iso[:13]+':00:00+00:00')
        except DomainError:
            # 无效时间行会在正式管线隔离，不参与影响范围判定
            continue
    return buckets

def _same_calculation(a,b):
    keys=('id','lower','upper','width','triple_lower','triple_upper','code')
    return all(a.get(k)==b.get(k) for k in keys)

def supplement(base_state,patch_content):
    """小时补录：合并后全量重算，但只接受受影响小时桶的变化。

    未受影响桶若与原批次计算结果不一致，说明补录越界影响了其他小时，
    直接拒绝，避免“补一行、全天重排”。任何失败都在落库前抛出，旧批次原样保留。
    """
    base_content=base64.b64decode(base_state['source_b64'])
    params=dict(base_state.get('manifest',{}).get('parameters',{}) or {})
    affected=_affected_buckets(patch_content)
    merged,base_line_count=_merge_content(base_content,patch_content)
    if len(merged)>2_000_000:raise DomainError('SIZE','合并后文件超过2MB',413)
    start=time.monotonic()
    state=None
    for n,entry in enumerate(MODULES,1):
        fn=importlib.import_module('app.modules.'+entry[0]+'.service').execute
        state=fn(merged,params) if n==1 else fn(state)
    before={c['id']:c for c in base_state.get('calculations',[])}
    after={c['id']:c for c in state['calculations']}
    untouched=set(before)-affected
    changed_outside=sorted(b for b in untouched if not _same_calculation(before[b],after.get(b,{})))
    if changed_outside:
        raise DomainError('RECOMPUTE','补录影响超出对应小时：'+','.join(changed_outside))
    state['supplement']={'affected_buckets':sorted(affected),'base_run_id':base_state['run_id'],
        'patch_lines':patch_content.count(b'\n'),'base_line_count':base_line_count}
    return _finalize(state,merged,params,time.monotonic()-start)
