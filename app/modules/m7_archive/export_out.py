import io,csv,json,hashlib

def bundle(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['记录类型','批次','来源行','业务ID','原因码','内容'])
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    gate=state.get('reconcile',{}).get('gate')
    if gate and gate.get('provided'):
        # 闸机总量仅作对证：封存与对账页采用同一结论，不收窄正式区间
        writer.writerow(['闸机对证',rid,'','',gate.get('status'),json.dumps(gate,ensure_ascii=False,sort_keys=True)])
    if state.get('supplement'):
        writer.writerow(['补录',rid,'','','',json.dumps(state['supplement'],ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):writer.writerow(['计算',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state['quarantine']:writer.writerow(['隔离',rid,row['line'],row.get('id',''),row['code'],json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '\ufeff'+out.getvalue()

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
