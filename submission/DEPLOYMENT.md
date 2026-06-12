# DEPLOYMENT.md

## Nhat Quang Day 12 AI Agent — Hướng dẫn Deploy

### Thông tin dự án

| | |
|---|---|
| **Tên app** | Nhat Quang Day 12 AI Agent |
| **Version** | 1.0.0 |
| **Stack** | FastAPI + Redis + Docker |
| **Public URL** | _(cập nhật sau khi deploy)_ |

---

## Chạy local

### 1. Cài dependencies

```bash
cd submission
pip install -r requirements.txt
```

### 2. Tạo file .env.local

```bash
cp .env.example .env.local
# Sửa AGENT_API_KEY thành key của bạn, ví dụ:
# AGENT_API_KEY=my-secret-key-2026
```

### 3. Chạy app

```bash
# Cách 1: Python trực tiếp
AGENT_API_KEY=my-secret-key-2026 uvicorn app.main:app --reload --port 8000

# Cách 2: Docker Compose (có Redis)
docker compose up
```

### 4. Test

```bash
# Health check
curl http://localhost:8000/health

# Hỏi agent (thay key đúng với .env.local)
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: my-secret-key-2026" \
  -d '{"question": "Docker là gì?"}'

# Metrics
curl http://localhost:8000/metrics \
  -H "X-API-Key: my-secret-key-2026"
```

---

## Deploy lên Railway (khuyến nghị — nhanh nhất)

### Bước 1: Cài Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### Bước 2: Khởi tạo project

```bash
cd submission
railway init
# Chọn "Create new project"
# Đặt tên: nhatquang290904-day12-ai-agent
```

### Bước 3: Set environment variables

```bash
railway variables set ENVIRONMENT=production
railway variables set AGENT_API_KEY=$(openssl rand -hex 32)
railway variables set JWT_SECRET=$(openssl rand -hex 32)
railway variables set DAILY_BUDGET_USD=5.0
railway variables set RATE_LIMIT_PER_MINUTE=20
```

### Bước 4: Deploy

```bash
railway up
```

### Bước 5: Lấy URL public

```bash
railway open
# URL dạng: https://nhatquang290904-day12-ai-agent-production.up.railway.app
```

### Bước 6: Test production

```bash
export PUBLIC_URL=https://nhatquang290904-day12-ai-agent-production.up.railway.app
export API_KEY=<key đã set ở bước 3>

curl $PUBLIC_URL/health
curl -X POST $PUBLIC_URL/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"question": "Bạn có thể làm gì?"}'
```

---

## Deploy lên Render (alternative)

### Bước 1: Push code lên GitHub

```bash
git add submission/
git commit -m "feat: add production AI agent submission"
git push
```

### Bước 2: Tạo service trên Render

1. Vào [render.com](https://render.com) → New → Blueprint
2. Connect GitHub repo
3. Render tự detect `render.yaml` và tạo service
4. Điền `AGENT_API_KEY` và `JWT_SECRET` trong dashboard

### Bước 3: Auto-deploy

Mỗi lần push lên `main` → Render tự build và deploy lại.

---

## Kiểm tra production readiness

```bash
cd day12_ha-tang-cloud_va_deployment
python 06-lab-complete/check_production_ready.py
```

Phải đạt **100%** trước khi nộp bài.

---

## Endpoints

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| GET | `/` | ❌ | App info |
| POST | `/ask` | ✅ X-API-Key | Hỏi agent |
| GET | `/health` | ❌ | Liveness probe |
| GET | `/ready` | ❌ | Readiness probe |
| GET | `/metrics` | ✅ X-API-Key | Usage metrics |
| GET | `/docs` | ❌ | Swagger UI (chỉ non-production) |

---

## Kiến trúc

```
Client
  │
  ▼
FastAPI app (uvicorn, 2 workers)
  ├── CORS middleware
  ├── Security headers middleware (logging + X-Content-Type-Options + remove Server)
  ├── API Key auth (X-API-Key header)
  ├── Rate limiter (sliding window, 20 req/min)
  ├── Cost guard (daily budget $5.00)
  └── Redis session storage (fallback: in-memory)
        │
        ▼
     Mock LLM (→ OpenAI khi có key thật)
```

---

## Screenshot

_(Thêm screenshot sau khi deploy thành công)_

```
GET /health → {"status":"ok","version":"1.0.0",...}
POST /ask   → {"answer":"...","session_id":"...","served_by":"agent-1"}
```
