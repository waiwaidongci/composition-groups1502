import redis
from ..config.settings import REDIS_URL

QUEUE_KEY = "composition:jobs"

def make_queue():
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=False,
    )

queue = make_queue()

def enqueue_run(run_id):
    """Push one accepted run id; callers decide whether a failure is fatal."""
    queue.rpush(QUEUE_KEY, str(run_id))

def take_run(timeout=2):
    """Pop the next accepted run id; returns None on timeout."""
    item = queue.blpop([QUEUE_KEY], timeout=timeout)
    return int(item[1]) if item else None

def pending_run_ids():
    """All ids currently waiting in the durable Redis list."""
    return {int(value) for value in queue.lrange(QUEUE_KEY, 0, -1)}
