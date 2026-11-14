import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .config.database import Base,engine
from .config.settings import SEED_DEMO
from . import models
from .routes import auth,studies,samples,components,runs,notes,audits
from .middlewares.errors import ErrorMiddleware
from .middlewares.rate_limit import RateLimitMiddleware
from .services.queue_service import queue
from .services.recovery_service import ensure_schema
from .services.inline_runner import inline_runner
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    ensure_schema()
    inline_runner.start()
    if SEED_DEMO:
        try:
            from scripts.seed_demo import seed
            seed()
        except Exception:logging.exception("demo seed failed")
    yield
    inline_runner.stop()
app=FastAPI(title="砺穗生物炭组成比较册",lifespan=lifespan)
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    details=[{"loc":[str(v) for v in e["loc"]],"msg":e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422,content={"detail":"；".join("/".join(e["loc"])+": "+e["msg"] for e in details)})
app.add_middleware(ErrorMiddleware);app.add_middleware(RateLimitMiddleware)
for module in [auth,studies,samples,components,runs,notes,audits]:app.include_router(module.router)
@app.get("/health")
def health():
    # The database is the acceptance record; a queue outage degrades delivery
    # but must not take the API down or hide already-accepted runs.
    with engine.connect() as c:c.execute(text("select 1"))
    try:queue.ping();queue_state="healthy"
    except Exception:queue_state="unavailable"
    return {"status":"healthy" if queue_state=="healthy" else "degraded","service":"composition-groups","queue":queue_state}
