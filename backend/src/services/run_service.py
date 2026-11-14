import csv,io
from fastapi import HTTPException
from ..models import CompositionRun,ResampleNote
from ..constants.status import RunStatus
from ..utils.serialize import record
from .study_service import get_study,create_snapshot
from .analysis_service import prepare_snapshot
from .audit_service import log
from . import queue_service
from .recovery_service import resolved_result, recovery_state

PUBLIC_LEASE_FIELDS = {"lease_token", "lease_expires_at", "lease_owner"}

def run_record(row):
    data = {key: value for key, value in record(row).items() if key not in PUBLIC_LEASE_FIELDS}
    data["recovery_state"] = recovery_state(row)
    data["recovery_reason"] = row.recovery_reason or ""
    data["attempts"] = int(row.attempts or 0)
    data["recovery_count"] = int(row.recovery_count or 0)
    data["result_hash"] = row.result_hash or ""
    data["artifact_key"] = row.artifact_key or ""
    data["finished_at"] = row.finished_at or ""
    data["approved_result_hash"] = row.approved_result_hash or ""
    data["approved_at"] = row.approved_at or ""
    # Display the published result row; export independently re-verifies the
    # artifact and the approval pin before producing CSV bytes.
    data["result"] = row.result if row.status == RunStatus.COMPLETED else {}
    return data

def list_runs(db):
    return [run_record(r) for r in db.query(CompositionRun).order_by(CompositionRun.id.desc())]

def get_run(db,rid):
    row=db.get(CompositionRun,rid)
    if not row:raise HTTPException(404,"组成运行不存在")
    return row

def create_run(db,data,user):
    study=get_study(db,data.study_id);snapshot=create_snapshot(db,study)
    try:
        prepare_snapshot(snapshot,data.delta)
        if len(snapshot['samples'])*data.permutations>150000:raise ValueError("样本数×置换数超额")
    except ValueError as e:raise HTTPException(422,str(e))
    row=CompositionRun(**data.model_dump(),input_snapshot=snapshot,owner=user.name,status=RunStatus.QUEUED)
    db.add(row);db.flush();log(db,user.email,'composition.enqueue',row.id);db.commit()
    # The committed row is the durable acceptance record. A queue outage must not
    # lose it: leave it queued and let the recovery sweep re-enqueue it.
    try:
        queue_service.enqueue_run(row.id)
    except Exception:
        row.recovery_reason='队列暂不可用，任务已受理并等待自动入队'
        db.commit()
    return run_record(row)

def export_run(db,rid):
    row=get_run(db,rid)
    approved=db.query(ResampleNote).filter_by(run_id=rid,status='approved').first()
    if row.status!=RunStatus.COMPLETED or not approved:raise HTTPException(403,'仅获批完成研究可导出')
    result,digest=resolved_result(row)
    if not result:raise HTTPException(409,'完成结果文件校验失败，暂不能导出')
    if row.approved_result_hash and digest!=row.approved_result_hash:
        raise HTTPException(409,'获批结果与当前完成结果不一致，已阻止导出')
    stats=result['statistics']
    o=io.StringIO();w=csv.writer(o);w.writerow(['sample','group','component','raw','closed','replaced','CLR','zero_count','delta','R2','pseudo_F','F_status','global_p','B','seed','input_hash'])
    for s in result['transformed']:
        for i,c in enumerate(result['components']):
            w.writerow([s['sample']['code'],s['sample']['group'],c['code'],s['raw'][i],s['closed'][i],s['replaced'][i],s['clr'][i],s['zero_count'],result['delta'],stats['R2'],stats['F'],stats['F_status'],stats['p'],result['permutations'],result['seed'],result['input_hash']])
    return o.getvalue()

