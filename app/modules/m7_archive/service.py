from app.modules.m7_archive.export_out import checksum

def execute(state):
    rec=state.get('reconcile',{})
    # 封存就绪与对账页面同一判断：行数守恒且无待核对（含闸机总量越界）
    ready=bool(rec.get('balanced')) and not rec.get('pending',False)
    state['archive']={'sha256':checksum(state),'evidence_count':len(state.get('calculations',[]))+len(state['quarantine']),
        'ready':ready,'gate_status':rec.get('gate',{}).get('status'),
        'gate_label':rec.get('gate',{}).get('label')}
    return state
