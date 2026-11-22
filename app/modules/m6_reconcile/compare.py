from app.errors import DomainError

# 裁决：闸机日结总量是单点观测，只与人数区间做对证，不构成正式约束。
# 正式结果始终是满足全部区域交集约束的区间 [lower, upper]；
# 闸机总量落在区间内仅作“佐证一致”，落在区间外则保留两份矛盾证据并转待核对。
STATUS_LABELS={'WITHOUT_GATE':'未提供闸机总量','GATE_MATCH':'闸机总量佐证一致','GATE_MISMATCH':'闸机总量越出区间，待核对'}

def gate_total(parameters):
    if not parameters or 'gate_total' not in parameters:return None
    raw=parameters['gate_total']
    if raw is None:return None
    if isinstance(raw,bool):raise DomainError('GATE','闸机总量必须是非负整数')
    if isinstance(raw,int):value=raw
    else:
        try:
            text=str(raw).strip()
            if not text or not text.lstrip('+').isdigit():raise ValueError
            value=int(text)
        except (TypeError,ValueError):raise DomainError('GATE','闸机总量必须是非负整数')
    if value<0:raise DomainError('GATE','闸机总量必须是非负整数')
    return value

def gate_check(business,parameters):
    gate=gate_total(parameters)
    block={'provided':gate is not None,'gate_total':gate,
        'lower_total':business.get('total'),'upper_total':business.get('upper_total'),
        'status':'WITHOUT_GATE','label':STATUS_LABELS['WITHOUT_GATE'],
        'deviation':None,'adjudication':'EVIDENCE'}
    if gate is None:return block
    low,high=business['total'],business['upper_total']
    inside=low<=gate<=high
    block['status']='GATE_MATCH' if inside else 'GATE_MISMATCH'
    block['label']=STATUS_LABELS[block['status']]
    # 偏差仅作核对线索，不回写、不收窄正式区间
    block['deviation']=0 if inside else (gate-high if gate>high else gate-low)
    return block

def balance(state):
    accepted=len(state['rows']);isolated=len(state['quarantine'])
    accounted=accepted+isolated+state['blank_count']+state['header_count']+state['duplicate_count']
    counts_balanced=accounted==state['input_count']
    gate=gate_check(state.get('business',{}),state.get('parameters',{}))
    # 待核对：行数守恒失败，或闸机总量越出区间（证据冲突，不得伪造精确结论）
    pending=not counts_balanced or gate['status']=='GATE_MISMATCH'
    return {'input':state['input_count'],'accepted':accepted,'isolated':isolated,
        'blank':state['blank_count'],'headers':state['header_count'],'duplicates':state['duplicate_count'],
        'accounted':accounted,'balanced':counts_balanced,'pending':pending,
        'gate':gate,'business':state.get('business',{})}
