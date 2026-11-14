"""Single-run execution shared by the CLI worker and the inline fallback runner.

Both paths use the same claim/write/mark/publish protocol, so whichever process
follows a lost owner publishes exactly one verified result.
"""
import logging, os, threading, time, uuid
from pathlib import Path
from ..config.database import SessionLocal
from ..config.settings import ARTIFACT_DIR, WORKER_LEASE_SECONDS
from ..utils.clock import now
from .analysis_service import analyze_composition
from .audit_service import log
from .recovery_service import (
    artifact_filename, claim_run, fail_run, mark_saving, publish_result,
    recover_finished_artifact, renew_lease, write_artifact,
)

def heartbeat(name="heartbeat"):
    """Publish executor liveness; atomic so healthchecks never read half a file."""
    path = Path(ARTIFACT_DIR) / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(str(time.time()))
        os.replace(temporary, path)
    except OSError:
        logging.warning("heartbeat write failed", exc_info=True)

class LeaseKeeper:
    """Renew a claim's lease while the CPU-bound computation runs.

    If renewal fails, the owner knows it has been superseded and must discard
    its result instead of publishing late.
    """

    def __init__(self, run_id, token, attempt):
        self.run_id, self.token, self.attempt = run_id, token, attempt
        self.lost = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        interval = max(.5, WORKER_LEASE_SECONDS / 3)
        while not self.stopped.wait(interval):
            heartbeat()
            try:
                with SessionLocal() as db:
                    if not renew_lease(db, self.run_id, self.token, self.attempt):
                        self.lost.set()
                        logging.warning("run %s lease lost; stale worker will not publish", self.run_id)
                        return
            except Exception:
                logging.warning("run %s lease renewal failed transiently", self.run_id, exc_info=True)

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=5)
        return not self.lost.is_set()

def adopt_previous_artifact(claim):
    """Publish a complete artifact left behind by a crashed owner, if verifiable."""
    result = recover_finished_artifact(claim)
    if result is None:
        return False
    attempt = claim["recovered_attempt"]
    key = artifact_filename(claim["id"], attempt)
    with SessionLocal() as db:
        if not mark_saving(db, claim["id"], claim["token"], claim["attempt"], key):
            return False
        if not publish_result(db, claim["id"], claim["token"], claim["attempt"], key, result,
                              "完成结果文件已写出但状态未保存，接手后直接核对并发布该文件"):
            return False
        log(db, "worker", "composition.recovered", claim["id"])
        db.commit()
    return True

def process(run_id, owner, allow_takeover=True):
    """Claim one run and drive it to exactly one published result."""
    with SessionLocal() as db:
        claim = claim_run(db, run_id, owner, allow_takeover=allow_takeover)
    if not claim:
        return False
    token = claim["token"]
    try:
        if adopt_previous_artifact(claim):
            logging.info("run %s recovered from attempt %s artifact", run_id, claim["recovered_attempt"])
            return True
        if claim["takeover"]:
            with SessionLocal() as db:
                log(db, owner, "composition.retry", run_id)
                db.commit()
        logging.info("run %s attempt %s claimed by %s", run_id, claim["attempt"], owner)
        keeper = LeaseKeeper(run_id, token, claim["attempt"]).start()
        try:
            result = analyze_composition(claim["input_snapshot"], claim["delta"],
                                         claim["permutations"], claim["seed"])
        finally:
            lease_ok = keeper.stop()
        if not lease_ok:
            logging.warning("run %s result discarded: lease lost while computing", run_id)
            with SessionLocal() as db:
                log(db, owner, "composition.discarded_stale", run_id)
                db.commit()
            return False
        with SessionLocal() as db:
            if not renew_lease(db, run_id, token, claim["attempt"]):
                logging.warning("run %s result discarded: claim no longer current", run_id)
                return False
            key, _digest = write_artifact(run_id, claim["attempt"], result, claim["input_snapshot"],
                                          claim["delta"], claim["permutations"], claim["seed"])
            if not mark_saving(db, run_id, token, claim["attempt"], key):
                logging.warning("run %s artifact written but claim superseded; not publishing", run_id)
                return False
        with SessionLocal() as db:
            published = publish_result(db, run_id, token, claim["attempt"], key, result)
            if published:
                log(db, "worker", "composition.completed", run_id)
                db.commit()
                return True
            log(db, "worker", "composition.discarded_stale", run_id)
            db.commit()
            return False
    except Exception as error:
        logging.exception("run %s failed", run_id)
        with SessionLocal() as db:
            if fail_run(db, run_id, token, claim["attempt"], str(error)):
                log(db, "worker", "composition.failed", run_id)
                db.commit()
        return False
