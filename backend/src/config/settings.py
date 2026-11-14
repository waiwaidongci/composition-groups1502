import os
DATABASE_URL=os.environ.get("DATABASE_URL","mysql+pymysql://composition:composition@db/composition?charset=utf8mb4")
REDIS_URL=os.environ.get("REDIS_URL","redis://redis:6379/0")
JWT_SECRET=os.environ.get("JWT_SECRET","local-composition-groups-change-this-key")
SEED_DEMO=os.environ.get("SEED_DEMO","true").lower()=="true"
ARTIFACT_DIR=os.environ.get("ARTIFACT_DIR","/artifacts")
WORKER_HEARTBEAT_SECONDS=max(.2,float(os.environ.get("WORKER_HEARTBEAT_SECONDS","5")))
WORKER_LEASE_SECONDS=max(float(os.environ.get("WORKER_LEASE_SECONDS","30")),WORKER_HEARTBEAT_SECONDS*3)
WORKER_SWEEP_SECONDS=max(.2,float(os.environ.get("WORKER_SWEEP_SECONDS","2")))
WORKER_MAX_ATTEMPTS=max(1,int(os.environ.get("WORKER_MAX_ATTEMPTS","8")))
INLINE_RUNNER_ENABLED=os.environ.get("INLINE_RUNNER_ENABLED","true").lower()=="true"
