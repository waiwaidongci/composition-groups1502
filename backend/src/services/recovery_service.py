import json, logging, os, time, uuid
from pathlib import Path
from sqlalchemy import inspect, text, update
from ..config.database import SessionLocal, engine
from ..config.settings import ARTIFACT_DIR, WORKER_LEASE_SECONDS, WORKER_MAX_ATTEMPTS, WORKER_SWEEP_SECONDS
from ..constants.status import ACTIVE_RUN_STATUSES, RunStatus
from ..models import CompositionRun
from ..utils.clock import now
from .analysis_service import VERSION, fingerprint
from .audit_service import log
from . import queue_service

ARTIFACT_SCHEMA = "composition-result-v1"

# Columns added after the original single-worker schema. They are appended in
# place so archives created by the old schema stay readable and exportable.
RECOVERY_COLUMNS = [
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("lease_token", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("lease_owner", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("lease_expires_at", "DOUBLE NOT NULL DEFAULT 0"),
    ("claimed_at", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("artifact_written_at", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("artifact_key", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("result_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("finished_at", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("recovery_count", "INTEGER NOT NULL DEFAULT 0"),
    ("recovery_reason", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("approved_result_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("approved_at", "VARCHAR(64) NOT NULL DEFAULT ''"),
]

def _columns():
    return {column["name"] for column in inspect(engine).get_columns(CompositionRun.__tablename__)}

def ensure_schema():
    """Add recovery columns to an existing database without dropping data."""
    if not inspect(engine).has_table(CompositionRun.__tablename__):
        return
    for name, ddl in RECOVERY_COLUMNS:
        if name in _columns():
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {CompositionRun.__tablename__} ADD COLUMN {name} {ddl}"))
        except Exception:
            logging.exception("schema column %s could not be added", name)
    absent = [name for name, _ in RECOVERY_COLUMNS if name not in _columns()]
    if absent:
        raise RuntimeError("composition_runs 缺少恢复列：" + "、".join(absent))

def canonical_snapshot(snapshot):
    components = sorted(snapshot["components"], key=lambda component: component["position"])
    samples = sorted(snapshot["samples"], key=lambda sample: sample["code"])
    return {"study": snapshot["study"], "components": components, "samples": samples}

def expected_input_hash(snapshot, delta, permutations, seed):
    return fingerprint({"version": VERSION, "snapshot": canonical_snapshot(snapshot),
                        "delta": float(delta), "B": int(permutations), "seed": int(seed)})

def artifact_filename(run_id, attempt):
    return f"run-{run_id}-attempt-{attempt}.json"

def artifact_path(run_id, attempt):
    return Path(ARTIFACT_DIR) / artifact_filename(run_id, attempt)

def write_artifact(run_id, attempt, result, snapshot, delta, permutations, seed):
    """Atomically publish a complete result file for one ownership attempt."""
    envelope = {
        "schema": ARTIFACT_SCHEMA,
        "run_id": int(run_id),
        "attempt": int(attempt),
        "algorithm_version": VERSION,
        "input_hash": expected_input_hash(snapshot, delta, permutations, seed),
        "result_hash": fingerprint(result),
        "written_at": now(),
        "result": result,
    }
    path = artifact_path(run_id, attempt)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return path.name, envelope["result_hash"]

def validate_artifact(run_id, attempt, snapshot, delta, permutations, seed):
    """Return the stored result only when it is complete and frozen-input exact."""
    try:
        with open(artifact_path(run_id, attempt), encoding="utf-8") as handle:
            envelope = json.load(handle)
        if envelope.get("schema") != ARTIFACT_SCHEMA:
            return None
        if int(envelope.get("run_id")) != int(run_id) or int(envelope.get("attempt")) != int(attempt):
            return None
        result = envelope.get("result")
        if not isinstance(result, dict):
            return None
        if envelope.get("algorithm_version") != VERSION or result.get("algorithm_version") != VERSION:
            return None
        if envelope.get("result_hash") != fingerprint(result):
            return None
        expected = expected_input_hash(snapshot, delta, permutations, seed)
        if envelope.get("input_hash") != expected or result.get("input_hash") != expected:
            return None
        if (result.get("delta") != float(delta) or result.get("seed") != int(seed)
                or result.get("permutations") != int(permutations)):
            return None
        components = result.get("components")
        statistics = result.get("statistics")
        transformed = result.get("transformed")
        if not isinstance(components, list) or not isinstance(statistics, dict) or not isinstance(transformed, list):
            return None
        if len(transformed) != len(snapshot["samples"]) or len(components) != len(snapshot["components"]):
            return None
        if any(len(row.get("raw", [])) != len(components) or len(row.get("clr", [])) != len(components)
               for row in transformed):
            return None
        if statistics.get("n") != len(transformed):
            return None
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

def latest_valid_artifact(run_id, up_to_attempt, snapshot, delta, permutations, seed):
    """Newest complete artifact written for this run, ignoring further attempts."""
    for attempt in range(int(up_to_attempt), 0, -1):
        stored = validate_artifact(run_id, attempt, snapshot, delta, permutations, seed)
        if stored is not None:
            return attempt, stored
    return None, None

def resolved_result(row):
    """Return (result, digest) for a completed run, pinned to its stored hash.

    The artifact of the winning attempt is preferred; a tampered or mismatched
    file is never substituted. Archives predating artifacts stay readable from
    the database result.
    """
    if row.status != RunStatus.COMPLETED:
        return None, ""
    attempt = int(row.attempts or 0)
    candidates = []
    if row.artifact_key:
        try:
            candidates.append(int(Path(row.artifact_key).name.split("-attempt-")[1].split(".")[0]))
        except (IndexError, ValueError):
            pass
    if attempt:
        candidates.append(attempt)
    seen = set()
    for candidate in candidates:
        if candidate < 1 or candidate in seen:
            continue
        seen.add(candidate)
        stored = validate_artifact(row.id, candidate, row.input_snapshot, row.delta,
                                   row.permutations, row.seed)
        if stored is None:
            continue
        digest = fingerprint(stored)
        if row.result_hash and digest != row.result_hash:
            continue
        return stored, digest
    stored = row.result or None
    if not stored:
        return None, ""
    digest = fingerprint(stored)
    if row.result_hash and digest != row.result_hash:
        return None, ""
    return stored, digest

def recovery_state(row):
    if row.status == RunStatus.FAILED:
        return "failed"
    if row.status == RunStatus.COMPLETED:
        return "recovered" if (row.recovery_count or 0) > 0 or (row.attempts or 0) > 1 else "normal"
    if row.status == RunStatus.SAVING:
        return "saving"
    if row.status == RunStatus.RUNNING:
        return "recovering" if (row.attempts or 0) > 1 or (row.recovery_count or 0) > 0 else "normal"
    if row.status == RunStatus.QUEUED:
        return "queue_pending" if (row.recovery_count or 0) > 0 or (row.recovery_reason or "") else "normal"
    return "normal"

def _claim_values(token, owner, attempt, base_count):
    return {
        "status": RunStatus.RUNNING,
        "attempts": attempt,
        "lease_token": token,
        "lease_owner": owner,
        "lease_expires_at": time.time() + WORKER_LEASE_SECONDS,
        "claimed_at": now(),
        "finished_at": "",
        "error": "",
        "recovery_count": base_count,
    }

def claim_run(db, run_id, owner, allow_takeover=True):
    """Atomically take or re-take a run. Only one claim per generation wins.

    Claims compare attempts and lease_token, so an owner that lost its lease
    can never come back and publish over the successor's row.
    """
    row = db.get(CompositionRun, run_id)
    if not row:
        return None
    old_attempt = int(row.attempts or 0)
    old_token = row.lease_token or ""
    old_count = int(row.recovery_count or 0)
    takeover = row.status in ACTIVE_RUN_STATUSES
    if takeover and old_attempt >= WORKER_MAX_ATTEMPTS:
        return None
    if row.status == RunStatus.QUEUED:
        stmt = (update(CompositionRun)
                .where(CompositionRun.id == run_id,
                       CompositionRun.status == RunStatus.QUEUED,
                       CompositionRun.attempts == old_attempt,
                       CompositionRun.lease_token == old_token))
        values = _claim_values(uuid.uuid4().hex, owner, old_attempt + 1, old_count)
    elif takeover and allow_takeover and float(row.lease_expires_at or 0) <= time.time():
        stmt = (update(CompositionRun)
                .where(CompositionRun.id == run_id,
                       CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)),
                       CompositionRun.attempts == old_attempt,
                       CompositionRun.lease_token == old_token,
                       CompositionRun.lease_expires_at <= time.time()))
        values = _claim_values(uuid.uuid4().hex, owner, old_attempt + 1, old_count + 1)
        values["recovery_reason"] = f"接手者失联，租约过期；第{old_attempt + 1}次接手沿用冻结输入与随机条件"
    else:
        return None
    changed = db.execute(stmt.values(**values))
    db.commit()
    if changed.rowcount != 1:
        return None
    return {
        "id": int(row.id),
        "attempt": old_attempt + 1,
        "old_attempt": old_attempt,
        "token": values["lease_token"],
        "takeover": takeover,
        "previous_status": row.status,
        "input_snapshot": row.input_snapshot,
        "delta": row.delta,
        "permutations": int(row.permutations),
        "seed": int(row.seed),
    }

def renew_lease(db, run_id, token, attempt):
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == run_id,
                                CompositionRun.lease_token == token,
                                CompositionRun.attempts == attempt,
                                CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)))
                         .values(lease_expires_at=time.time() + WORKER_LEASE_SECONDS))
    db.commit()
    return changed.rowcount == 1

def mark_saving(db, run_id, token, attempt, artifact_key):
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == run_id,
                                CompositionRun.lease_token == token,
                                CompositionRun.attempts == attempt,
                                CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)))
                         .values(status=RunStatus.SAVING, artifact_key=artifact_key,
                                 artifact_written_at=now(),
                                 lease_expires_at=time.time() + WORKER_LEASE_SECONDS))
    db.commit()
    return changed.rowcount == 1

def publish_result(db, run_id, token, attempt, artifact_key, result, recovery_reason=""):
    values = {
        "status": RunStatus.COMPLETED,
        "result": result,
        "result_hash": fingerprint(result),
        "artifact_key": artifact_key,
        "finished_at": now(),
        "lease_token": "",
        "lease_owner": "",
        "lease_expires_at": 0,
        "error": "",
    }
    if recovery_reason:
        values["recovery_reason"] = recovery_reason[:500]
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == run_id,
                                CompositionRun.lease_token == token,
                                CompositionRun.attempts == attempt,
                                CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)))
                         .values(**values))
    db.commit()
    return changed.rowcount == 1

def fail_run(db, run_id, token, attempt, error):
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == run_id,
                                CompositionRun.lease_token == token,
                                CompositionRun.attempts == attempt,
                                CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)))
                         .values(status=RunStatus.FAILED, error=(error or "计算失败")[:4000],
                                 finished_at=now(), lease_token="", lease_owner="",
                                 lease_expires_at=0))
    db.commit()
    return changed.rowcount == 1

def recover_finished_artifact(claim):
    """Adopt a verified artifact left by the interrupted owner, without recomputing."""
    if not claim["takeover"]:
        return None
    attempt, result = latest_valid_artifact(claim["id"], claim["old_attempt"],
                                            claim["input_snapshot"], claim["delta"],
                                            claim["permutations"], claim["seed"])
    if result is None:
        return None
    claim["recovered_attempt"] = attempt
    return result

def publish_completed_run(db, row):
    """Publish a verified artifact written before the completion state was saved.

    Adoption is idempotent and pinned to the artifact; it never recomputes and
    never changes the frozen input or random conditions.
    """
    if row.status == RunStatus.COMPLETED:
        return True
    if row.status not in ACTIVE_RUN_STATUSES:
        return False
    attempt, result = latest_valid_artifact(row.id, int(row.attempts or 0),
                                            row.input_snapshot, row.delta,
                                            row.permutations, row.seed)
    if result is None:
        return False
    key = artifact_filename(row.id, attempt)
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == row.id,
                                CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)))
                         .values(status=RunStatus.COMPLETED,
                                 result=result,
                                 result_hash=fingerprint(result),
                                 artifact_key=key,
                                 finished_at=now(),
                                 lease_token="", lease_owner="", lease_expires_at=0,
                                 recovery_count=int(row.recovery_count or 0) + 1,
                                 recovery_reason="结果文件写出后、完成状态保存前中断；已核对冻结输入并发布该文件"))
    db.commit()
    return changed.rowcount == 1

def _requeue(db, row_id, statuses, observed_attempt, reason, owner, extra_where):
    """Put one lost run back on the queue; the guarded update runs after the push."""
    try:
        queue_service.enqueue_run(row_id)
    except Exception:
        logging.warning("composition queue unavailable for recovery of run %s", row_id, exc_info=True)
        return False
    changed = db.execute(update(CompositionRun)
                         .where(CompositionRun.id == row_id,
                                CompositionRun.status.in_(list(statuses)),
                                CompositionRun.attempts == observed_attempt,
                                *extra_where)
                         .values(recovery_count=CompositionRun.recovery_count + 1,
                                 recovery_reason=reason))
    db.commit()
    if changed.rowcount != 1:
        return False
    # Duplicate queue entries are harmless: claim_run accepts exactly one owner.
    log(db, owner, "composition.requeued", row_id)
    db.commit()
    return True

def sweep(owner):
    """Repair accepted runs whose queue entry or owner disappeared.

    The database is the durable record: a queued row missing from Redis is put
    back, and an expired lease is queued for a new owner. This function publishes
    only artifacts already proven complete by the interrupted owner.
    """
    with SessionLocal() as db:
        try:
            pending = queue_service.pending_run_ids()
        except Exception:
            logging.warning("composition queue unavailable during recovery sweep", exc_info=True)
            return
        rows = (db.query(CompositionRun)
                .filter(CompositionRun.status.in_([RunStatus.QUEUED, *ACTIVE_RUN_STATUSES]))
                .all())
        for row in rows:
            observed_attempt = int(row.attempts or 0)
            if row.status in ACTIVE_RUN_STATUSES and observed_attempt and float(row.lease_expires_at or 0) <= time.time():
                # A complete file is proof the computation finished; adopt it
                # before requeueing so a saving-phase crash never recomputes.
                if publish_completed_run(db, row):
                    log(db, owner, "composition.recovered", row.id)
                    db.commit()
                    continue
            if row.status == RunStatus.QUEUED:
                if row.id in pending:
                    continue
                _requeue(db, row.id, [RunStatus.QUEUED], observed_attempt,
                         "队列断连后任务仍在数据库，已自动重新入队", owner, [])
                continue
            if float(row.lease_expires_at or 0) > time.time():
                continue
            if row.id in pending:
                continue
            if observed_attempt >= WORKER_MAX_ATTEMPTS:
                failed = db.execute(update(CompositionRun)
                                    .where(CompositionRun.id == row.id,
                                           CompositionRun.status.in_(list(ACTIVE_RUN_STATUSES)),
                                           CompositionRun.attempts == observed_attempt,
                                           CompositionRun.lease_expires_at <= time.time())
                                    .values(status=RunStatus.FAILED,
                                            error=f"自动恢复已达上限（{WORKER_MAX_ATTEMPTS}次接手），最近一次接手未留下完整结果",
                                            finished_at=now(), lease_token="", lease_owner="",
                                            lease_expires_at=0))
                db.commit()
                if failed.rowcount == 1:
                    log(db, owner, "composition.recovery_failed", row.id)
                    db.commit()
                continue
            _requeue(db, row.id, ACTIVE_RUN_STATUSES, observed_attempt,
                     "接手者租约过期，已自动重新排队等待新进程接手", owner,
                     [CompositionRun.lease_expires_at <= time.time()])

def pin_approval(db, row):
    """Bind approval to the exact completed result that export will read."""
    result, digest = resolved_result(row)
    if result is None:
        return None
    row.approved_result_hash = digest
    row.approved_at = now()
    return digest
