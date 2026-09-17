"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db.engine import create_all

app = FastAPI(
    title="AI Purchasing Agent",
    description=(
        "The agent proposes; a deterministic engine decides feasibility; a policy "
        "gate authorises; an idempotent executor acts; an independent validator "
        "checks what actually happened."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    create_all()
