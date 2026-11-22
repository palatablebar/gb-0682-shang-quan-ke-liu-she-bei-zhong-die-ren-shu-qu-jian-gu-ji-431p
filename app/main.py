import importlib,os
from flask import Flask,jsonify,request,redirect,Response
from app.config import MODULES
from app.errors import DomainError
from app.workflow import run,load,supplement
from app import store
from app.web import payload
from app.modules.m7_archive.export_out import bundle

def create_app():
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=2_000_000
    for entry in MODULES:app.register_blueprint(importlib.import_module('app.modules.'+entry[0]+'.handler').bp)
    @app.errorhandler(DomainError)
    def domain_error(error):return jsonify(code=error.code,message=error.message),error.status
    @app.errorhandler(404)
    def missing(error):return jsonify(code='NOT_FOUND',message='入口不存在'),404
    @app.get('/')
    def index():return redirect('/'+MODULES[0][0])
    @app.get('/healthz')
    def health():return jsonify(status='ok')
    @app.post('/api/runs')
    def submit():
        content,params=payload();state=run(content,params);return jsonify(store.save(state['run_id'],state))
    @app.get('/api/runs')
    def list_runs():return jsonify(store.history())
    @app.get('/api/runs/<run_id>')
    def get_run(run_id):return jsonify(store.get(run_id))
    @app.post('/api/runs/<run_id>/review')
    def review(run_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data.get('version'),int):raise DomainError('VERSION','请提交复核版本')
        return jsonify(store.review(run_id,data['version'],data.get('decision')))
    @app.post('/api/runs/<run_id>/supplement')
    def supplement_run(run_id):
        data=request.get_json(silent=True) or {}
        patch=data.get('csv')
        if not isinstance(patch,str) or not patch.strip():raise DomainError('PAYLOAD','补录必须提交CSV文本')
        base=store.get(run_id)
        # 补录失败（RECOMPUTE/HEADER等）在落库前抛出，旧批次原样保留、记录不丢失
        new_state=supplement(base,patch.encode('utf-8'))
        return jsonify(store.replace_latest(new_state))
    @app.get('/api/archive/<run_id>/export.csv')
    def download(run_id):
        state=store.get(run_id)
        rec=state.get('reconcile',{})
        if not rec.get('balanced') or rec.get('pending'):raise DomainError('UNBALANCED','对账未平或待核对，不能封存')
        return Response(bundle(state),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=evidence.csv'})
    with app.app_context():
        if not store.history():
            state=run(load('dirty.csv'),{});store.save(state['run_id'],state)
    return app

app=create_app()
if __name__=='__main__':app.run(host='0.0.0.0',port=8000)
