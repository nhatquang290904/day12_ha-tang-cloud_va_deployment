"""
Production AI Agent — Nhat Quang (Day 12 Lab)

Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting (sliding window)
  ✅ Cost guard (daily budget)
  ✅ Input validation (Pydantic)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown (SIGTERM)
  ✅ Security headers
  ✅ CORS
  ✅ Redis session storage (với fallback in-memory)
  ✅ Error handling
"""
import os
import time
import signal
import logging
import json
import uuid
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional

import redis as redis_lib
from fastapi import FastAPI, HTTPException, Security, Depends, Request, Response
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings

# Mock LLM — thay bằng OpenAI/Anthropic khi có key thật
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.mock_llm import ask as llm_ask

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# Redis (optional) — fallback sang in-memory nếu không có
# ─────────────────────────────────────────────────────────
_redis: Optional[redis_lib.Redis] = None
_memory_sessions: dict = {}  # fallback khi không có Redis

def get_redis() -> Optional[redis_lib.Redis]:
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        return None
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        r.ping()
        _redis = r
        logger.info(json.dumps({"event": "redis_connected", "url": settings.redis_url}))
        return _redis
    except Exception as e:
        logger.warning(json.dumps({"event": "redis_unavailable", "error": str(e), "fallback": "in-memory"}))
        return None

def load_history(session_id: str) -> list:
    r = get_redis()
    if r:
        raw = r.get(f"session:{session_id}")
        return json.loads(raw) if raw else []
    return _memory_sessions.get(session_id, [])

def save_history(session_id: str, history: list):
    history = history[-20:]  # giới hạn 20 messages
    r = get_redis()
    if r:
        r.setex(f"session:{session_id}", 3600, json.dumps(history))
    else:
        _memory_sessions[session_id] = history

# ─────────────────────────────────────────────────────────
# Rate Limiter — Sliding window per API key
# ─────────────────────────────────────────────────────────
_rate_windows: dict[str, deque] = defaultdict(deque)

def check_rate_limit(key: str):
    now = time.time()
    window = _rate_windows[key]
    # Xoá các request cũ hơn 60 giây
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min. Try again in 60s.",
            headers={"Retry-After": "60"},
        )
    window.append(now)

# ─────────────────────────────────────────────────────────
# Cost Guard — Daily budget
# ─────────────────────────────────────────────────────────
_daily_cost = 0.0
_cost_reset_day = time.strftime("%Y-%m-%d")

def check_and_record_cost(input_tokens: int, output_tokens: int):
    global _daily_cost, _cost_reset_day
    today = time.strftime("%Y-%m-%d")
    if today != _cost_reset_day:
        _daily_cost = 0.0
        _cost_reset_day = today
        logger.info(json.dumps({"event": "budget_reset", "day": today}))
    if _daily_cost >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=503,
            detail=f"Daily budget ${settings.daily_budget_usd} exhausted. Resets tomorrow.",
        )
    # gpt-4o-mini pricing (approximate)
    cost = (input_tokens / 1_000_000) * 0.15 + (output_tokens / 1_000_000) * 0.60
    _daily_cost += cost

# ─────────────────────────────────────────────────────────
# Auth — API Key
# ─────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Add header: X-API-Key: <key>",
        )
    return api_key

# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }))
    # Kết nối Redis sớm
    get_redis()
    time.sleep(0.1)  # simulate init delay
    _is_ready = True
    logger.info(json.dumps({"event": "ready", "instance": os.getenv("INSTANCE_ID", "local")}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown", "total_requests": _request_count}))

# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production AI Agent — Day 12 Lab (Nhat Quang)",
    lifespan=lifespan,
    # Tắt /docs trong production
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def security_and_logging_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if "server" in response.headers:
            del response.headers["server"]  # Ẩn server info
        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration_ms,
        }))
        return response
    except Exception as e:
        _error_count += 1
        raise

# ─────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="Câu hỏi gửi cho agent")
    session_id: Optional[str] = Field(None, description="Session ID để giữ conversation history")

class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    session_id: str
    timestamp: str
    served_by: str

# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask":     "POST /ask  (requires X-API-Key)",
            "health":  "GET  /health",
            "ready":   "GET  /ready",
            "metrics": "GET  /metrics  (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Gửi câu hỏi cho AI agent.

    - **question**: Câu hỏi của bạn (tối đa 2000 ký tự)
    - **session_id**: (tuỳ chọn) ID phiên để giữ lịch sử hội thoại
    - Header **X-API-Key** bắt buộc
    """
    # Rate limit theo API key bucket
    check_rate_limit(_key[:8])

    # Ước tính token & kiểm tra budget
    input_tokens = len(body.question.split()) * 2
    check_and_record_cost(input_tokens, 0)

    # Lấy / tạo session
    session_id = body.session_id or str(uuid.uuid4())
    history = load_history(session_id)

    logger.info(json.dumps({
        "event": "agent_call",
        "session_id": session_id,
        "q_len": len(body.question),
        "history_len": len(history),
        "client": str(request.client.host) if request.client else "unknown",
    }))

    # Gọi LLM
    answer = llm_ask(body.question)

    # Ghi lại cost output
    output_tokens = len(answer.split()) * 2
    check_and_record_cost(0, output_tokens)

    # Lưu history
    history.append({"role": "user",      "content": body.question})
    history.append({"role": "assistant", "content": answer})
    save_history(session_id, history)

    return AskResponse(
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        served_by=os.getenv("INSTANCE_ID", "local"),
    )


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe — platform khởi động lại container nếu endpoint này fail."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "storage": "redis" if get_redis() else "in-memory",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe — load balancer ngừng gửi traffic nếu trả về 503."""
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"ready": True, "instance": os.getenv("INSTANCE_ID", "local")}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Metrics cơ bản (yêu cầu auth)."""
    return {
        "uptime_seconds":    round(time.time() - START_TIME, 1),
        "total_requests":    _request_count,
        "error_count":       _error_count,
        "daily_cost_usd":    round(_daily_cost, 6),
        "daily_budget_usd":  settings.daily_budget_usd,
        "budget_used_pct":   round(_daily_cost / settings.daily_budget_usd * 100, 2),
        "rate_limit":        f"{settings.rate_limit_per_minute} req/min",
        "storage":           "redis" if get_redis() else "in-memory",
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_sigterm(signum, _frame):
    logger.info(json.dumps({"event": "sigterm_received", "signum": signum}))

signal.signal(signal.SIGTERM, _handle_sigterm)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
