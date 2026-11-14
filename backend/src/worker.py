import logging, os, socket, time, uuid
from .config.database import Base, engine
from .config.settings import WORKER_SWEEP_SECONDS
from .services import queue_service
from .services.recovery_service import ensure_schema, sweep
from .services.runner_service import heartbeat, process

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def owner_name():
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

def main():
    Base.metadata.create_all(engine)
    ensure_schema()
    owner = owner_name()
    logging.info("composition worker %s started", owner)
    heartbeat()
    last_sweep = 0.0
    while True:
        heartbeat()
        if time.monotonic() - last_sweep >= WORKER_SWEEP_SECONDS:
            try:
                sweep(owner)
            except Exception:
                logging.warning("recovery sweep failed", exc_info=True)
            last_sweep = time.monotonic()
        try:
            run_id = queue_service.take_run(timeout=2)
        except Exception:
            logging.warning("composition queue unavailable; retrying", exc_info=True)
            time.sleep(1)
            continue
        if run_id is None:
            continue
        process(run_id, owner)

if __name__ == "__main__":
    main()
