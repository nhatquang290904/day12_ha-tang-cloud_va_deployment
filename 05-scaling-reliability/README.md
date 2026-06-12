# 05 — Scaling & Reliability

Hai kỹ năng cốt lõi để deploy AI Agent lên môi trường production:

1. **Health checks + Graceful shutdown** — agent tự báo cáo trạng thái, tắt không mất request
2. **Stateless design** — lưu session vào Redis để scale ngang tự do

---

## Cấu trúc

```
05-scaling-reliability/
├── develop/          # Bước 1: Health check & graceful shutdown (chạy local)
│   ├── app.py
│   ├── requirements.txt
│   └── utils/mock_llm.py
└── production/       # Bước 2: Stateless agent + Redis + Nginx (Docker Compose)
    ├── app.py
    ├── docker-compose.yml
    ├── nginx.conf
    ├── test_stateless.py
    └── utils/mock_llm.py
```

---

## Bước 1 — Health Check & Graceful Shutdown (`develop/`)

### Khái niệm

| Endpoint  | Mục đích | Platform dùng để làm gì |
|-----------|----------|------------------------|
| `GET /health` | **Liveness probe** — agent còn sống không? | Restart container nếu fail |
| `GET /ready`  | **Readiness probe** — agent sẵn sàng nhận traffic chưa? | Tắt route traffic nếu fail |

### Kiến trúc bên trong `app.py`

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI App                        │
├─────────────────────────────────────────────────────┤
│  Lifespan (startup/shutdown)                         │
│    • Startup:  load model → _is_ready = True         │
│    • Shutdown: _is_ready = False → chờ in-flight → exit│
├─────────────────────────────────────────────────────┤
│  Middleware: track_requests                          │
│    • Mỗi request đến → _in_flight_requests += 1     │
│    • Request xong    → _in_flight_requests -= 1     │
├─────────────────────────────────────────────────────┤
│  Endpoints                                           │
│    • GET  /health  → liveness (status, uptime, mem)  │
│    • GET  /ready   → readiness (503 nếu chưa sẵn sàng)│
│    • POST /ask     → business logic (hỏi AI)        │
├─────────────────────────────────────────────────────┤
│  Signal Handlers                                     │
│    • SIGTERM / SIGINT → log + uvicorn tự shutdown    │
└─────────────────────────────────────────────────────┘
```

### Flow Graceful Shutdown

```
Platform gửi SIGTERM
  → handle_sigterm() log thông tin
  → uvicorn trigger lifespan shutdown
    → _is_ready = False
      (endpoint /ready trả 503 → load balancer ngừng gửi traffic mới)
    → chờ _in_flight_requests == 0 (tối đa 30 giây)
    → shutdown hoàn tất, process exit
```

### Các thành phần chính

| Thành phần | Vai trò |
|---|---|
| `lifespan()` | Context manager quản lý startup (load model) và shutdown (chờ request) |
| `track_requests` middleware | Đếm số request đang xử lý, phối hợp với shutdown logic |
| `_is_ready` flag | Cờ readiness, `False` khi startup chưa xong hoặc đang shutdown |
| `_in_flight_requests` counter | Đếm request đang xử lý, shutdown chờ counter về 0 |
| `handle_sigterm()` | Bắt SIGTERM/SIGINT, uvicorn tự trigger lifespan shutdown |

### Chạy

```bash
cd develop
pip install -r requirements.txt
python app.py
```

### Test Health Check

```bash
# Liveness
curl http://localhost:8000/health

# Readiness
curl http://localhost:8000/ready

# Hỏi agent (mock delay 3 giây)
curl -X POST "http://localhost:8000/ask?question=hello"
```

### Test Graceful Shutdown

Mục tiêu: chứng minh server **không mất request** khi nhận SIGTERM.

**Terminal 1** — chạy server:
```bash
cd develop
source venv/bin/activate
python app.py
# → ghi nhớ PID hiển thị trong log: "Started server process [PID]"
```

**Terminal 2** — gửi request rồi kill server ngay khi đang xử lý:
```bash
# Gửi 2 request song song (mỗi cái mất ~3 giây) rồi SIGTERM ngay sau 0.5 giây
curl -s -X POST "http://localhost:8000/ask?question=hello" &
curl -s -X POST "http://localhost:8000/ask?question=hello" &
sleep 0.5 && kill -SIGTERM <PID>
wait
```

**Kết quả mong đợi:**

- Terminal 2: cả 2 request đều trả về response `200 OK` (không bị cắt)
- Terminal 1 (server log):

```
INFO:     Shutting down
INFO:     127.0.0.1:... - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:... - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-06-10 ... INFO 🔄 Graceful shutdown initiated...
2026-06-10 ... INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [PID]
2026-06-10 ... INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Giải thích flow:**

```
t=0.0s  Request 1 & 2 gửi đến → in_flight_requests = 2
t=0.5s  SIGTERM gửi đến → server bắt đầu shutdown
        → _is_ready = False (từ chối request mới, /ready trả 503)
        → nhưng KHÔNG tắt ngay, chờ 2 request đang xử lý...
t=3.0s  Request 1 & 2 hoàn thành → in_flight_requests = 0
        → server tắt an toàn, không mất data
```

**Ví dụ response `/health`:**
```json
{
  "status": "ok",
  "uptime_seconds": 76.4,
  "version": "1.0.0",
  "environment": "development",
  "timestamp": "2026-06-10T07:20:39.887711+00:00",
  "checks": {
    "memory": {
      "status": "ok",
      "used_percent": 76.5
    }
  }
}
```

**Ví dụ response `/ready`:**
```json
{
  "ready": true,
  "in_flight_requests": 2
}
```

---

## Bước 2 — Stateless Agent + Redis (`production/`)

### Vấn đề khi scale stateful

```
Instance 1: User A → request 1 → lưu session trong memory ✅
Instance 2: User A → request 2 → KHÔNG thấy session ❌ Bug!
```

### Giải pháp: Stateless + Redis

```
Instance 1: User A → request 1 → lưu session vào Redis ✅
Instance 2: User A → request 2 → đọc session từ Redis ✅
```

Bất kỳ instance nào cũng phục vụ được bất kỳ user nào.

### Kiến trúc

```
Client → Nginx (port 8080) → Round-robin → Agent Instance 1
                                         → Agent Instance 2
                                         → Agent Instance 3
                                               ↕
                                            Redis
```

### Chạy

```bash
cd production
docker compose up --scale agent=3
```

### Test

```bash
# Chạy test script (sau khi docker compose up xong)
python test_stateless.py
```

Output mẫu:
```
Session ID: abc-123-...

Request 1: [instance-a1b2c3]  ← instance khác nhau
Request 2: [instance-d4e5f6]
Request 3: [instance-a1b2c3]

✅ All requests served despite different instances!
✅ Session history preserved across all instances via Redis!
```

### API

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/chat` | Gửi câu hỏi, nhận `session_id` ở response đầu tiên |
| `GET`  | `/chat/{session_id}/history` | Xem toàn bộ lịch sử hội thoại |
| `DELETE` | `/chat/{session_id}` | Xóa session |
| `GET`  | `/health` | Health check (bao gồm Redis status) |
| `GET`  | `/ready` | Readiness check |

**Ví dụ multi-turn:**
```bash
# Turn 1 — không có session_id
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Docker?"}'
# → trả về session_id: "abc-123"

# Turn 2 — gửi kèm session_id
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Tell me more", "session_id": "abc-123"}'
```

---

## Điểm khác nhau giữa develop và production

| | `develop/` | `production/` |
|---|---|---|
| State | Stateful (in-memory) | Stateless (Redis) |
| Scale | 1 instance | N instances |
| Session | Mất khi restart | Bền vững, TTL 1 giờ |
| Load balancer | Không có | Nginx round-robin |
| Deploy | `python app.py` | `docker compose up --scale agent=3` |
