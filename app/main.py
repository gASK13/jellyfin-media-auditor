from __future__ import annotations
import logging
import threading
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from app.config import load_config
from app.db.database import make_session_factory
from app.jellyfin.client import JellyfinClient
from app.jellyfin.scanner import reconcile, upsert_item
from app.jobs.queue import claim_next
from app.jobs.worker import Worker, recover_orphaned_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
config=load_config(); Session=make_session_factory(config.db_path); client=JellyfinClient(config.jellyfin_url, config.jellyfin_api_key, config.jellyfin_user_id)

def run_loop() -> None:
    worker=Worker(config, jellyfin_client=client); next_scan=0.0
    while True:
        try:
            if time.monotonic() >= next_scan:
                with Session.begin() as session:
                    reconcile(session, config, client)
                next_scan=time.monotonic()+config.scanner_interval_minutes*60
            job=None
            with Session.begin() as session:
                job=claim_next(session)
            if job:
                with Session.begin() as session:
                    worker.process(session, job)
        except Exception: logging.exception("worker loop failed")
        time.sleep(config.worker_poll_seconds)

@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session.begin() as session:
        recover_orphaned_jobs(session)
    threading.Thread(target=run_loop, daemon=True, name="auditor-worker").start(); yield

app=FastAPI(title="jellyfin-media-auditor", lifespan=lifespan)

@app.get("/health")
def health(): return {"status":"ok"}

@app.post("/webhook/jellyfin")
async def jellyfin_webhook(request: Request):
    if config.webhook_token and request.headers.get("X-Auditor-Token") != config.webhook_token: raise HTTPException(401, "Invalid webhook token")
    payload=await request.json(); item_id=payload.get("ItemId") or payload.get("item_id") or payload.get("Item", {}).get("Id")
    if not item_id: return {"ignored":"no item id"}
    item=client.get_item(item_id)
    if item.get("Type") != "Movie": return {"ignored":"not a movie"}
    library=next((lib for lib in config.libraries if lib.jellyfin_id == item.get("ParentId")), config.libraries[0] if config.libraries else None)
    if not library: return {"ignored":"no matching configured library"}
    with Session.begin() as session: upsert_item(session, config, library, item)
    return {"queued": item_id}
