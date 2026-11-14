from enum import StrEnum
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SAVING = "saving"
    COMPLETED = "completed"
    FAILED = "failed"
ACTIVE_RUN_STATUSES = (RunStatus.RUNNING, RunStatus.SAVING)
