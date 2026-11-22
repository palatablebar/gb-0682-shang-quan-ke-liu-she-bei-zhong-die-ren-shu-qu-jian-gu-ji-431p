import sqlite3,json,os
from pathlib import Path
from app.errors import DomainError

def connection():
    path=Path(os.environ.get('DB_PATH','data/records.db'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    return db

def save(run_id, body):
    with connection() as db:
        # 同批重跑（幂等键相同）复用既有行，不新增对账版本、不改复核结论
        db.execute('INSERT OR IGNORE INTO runs(id,body) VALUES (?,?)',(run_id,json.dumps(body,ensure_ascii=False)))
        db.execute("INSERT INTO meta(key,value) VALUES ('latest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(run_id,))
    return get(run_id)

def get(run_id):
    with connection() as db:r=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not r:raise DomainError('NOT_FOUND','批次不存在',404)
    body=json.loads(r['body']);body.update(run_id=r['id'],review_version=r['version'],decision=r['decision']);return body

def history():
    with connection() as db:rows=db.execute("SELECT id,version,decision FROM runs ORDER BY CASE WHEN id=(SELECT value FROM meta WHERE key='latest') THEN 0 ELSE 1 END,rowid DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]

def review(run_id, version, decision):
    if decision not in ('通过','退回'):raise DomainError('DECISION','复核状态无效')
    with connection() as db:
        if decision=='通过':
            row=db.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()
            if not row:raise DomainError('NOT_FOUND','批次不存在',404)
            body=json.loads(row['body'])
            rec=body.get('reconcile',{})
            if not rec.get('balanced') or rec.get('pending'):
                raise DomainError('REVIEW','对账未平或闸机总量待核对，不能复核通过')
        cur=db.execute('UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?',(decision,run_id,version))
        if cur.rowcount!=1:
            if not db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():raise DomainError('NOT_FOUND','批次不存在',404)
            raise DomainError('STALE','复核版本已更新，请刷新',409)
    return get(run_id)

def replace_latest(new_body):
    """把当前批次切换为补录重算结果。

    先在独立事务里完成新批次落库并校验记录完整，再切换 latest 指针；
    任一步失败都不触碰旧批次——旧版始终可读，记录不会丢失。
    新旧 run_id 相同（同批重跑）时只刷新正文，不产生新版本行。
    """
    new_id=new_body['run_id']
    with connection() as db:
        latest=db.execute("SELECT value FROM meta WHERE key='latest'").fetchone()
        old_id=latest['value'] if latest else None
        old=db.execute('SELECT body FROM runs WHERE id=?',(old_id,)).fetchone() if old_id else None
        old_body=json.loads(old['body']) if old else None
        if old_body is not None:
            _ensure_no_record_lost(old_body,new_body)
        db.execute('INSERT OR IGNORE INTO runs(id,body) VALUES (?,?)',(new_id,json.dumps(new_body,ensure_ascii=False)))
        if not db.execute('SELECT 1 FROM runs WHERE id=?',(new_id,)).fetchone():
            raise DomainError('SWITCH','补录批次落库失败，已保留旧版')
        db.execute("INSERT INTO meta(key,value) VALUES ('latest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(new_id,))
    return get(new_id)

def _ensure_no_record_lost(old,new):
    # 记录守恒：原始输入行、隔离证据、计算桶证据只能增加或保持，不得因切换丢失
    if new.get('input_count',0)<old.get('input_count',0):
        raise DomainError('SWITCH','补录后输入记录数减少，已保留旧版')
    if len(new.get('quarantine',[]))<len(old.get('quarantine',[])):
        raise DomainError('SWITCH','补录后隔离证据减少，已保留旧版')
    old_keys={(c['id'],c['line']) for c in old.get('calculations',[])}
    new_keys={(c['id'],c['line']) for c in new.get('calculations',[])}
    if old_keys-new_keys:
        raise DomainError('SWITCH','补录后丢失原有小时计算证据，已保留旧版')
