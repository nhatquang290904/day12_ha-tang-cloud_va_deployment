# MISSION_ANSWERS.md — Trả lời bài tập Part 1-5

## Part 1: Localhost vs Production

### Exercise 1.1: Tìm 5 anti-patterns trong `develop/app.py`

1. **Hardcoded API Key** — `OPENAI_API_KEY = "sk-proj-abc123..."` lộ secret ngay trong source code. Nếu push lên GitHub → bị bot scan và sử dụng trái phép trong vài phút.

2. **Hardcoded database password** — `DB_PASSWORD = "admin123"` tương tự, ai có access vào repo đều đọc được.

3. **DEBUG = True trong production** — Hiển thị full traceback cho attacker, bao gồm cả nội bộ đường dẫn file, biến, và logic xử lý.

4. **Dùng print() thay vì structured logging** — Không có timestamp, log level, không parse được bằng tool (Datadog, CloudWatch). Tệ hơn: `print(f"API Key: {OPENAI_API_KEY}")` log ra cả secret.

5. **Bind `127.0.0.1` (localhost only)** — Trong Docker container hoặc cloud, traffic đến từ bên ngoài network namespace → app không nhận được request nào. Phải dùng `0.0.0.0`.

### Exercise 1.2: Tại sao cần `/health` endpoint?

- **Kubernetes/Cloud Run** dùng health check để biết container còn sống không. Nếu `/health` fail liên tiếp → tự động restart.
- **Load balancer** dùng `/ready` để ngừng route traffic đến instance đang khởi động hoặc đang shutdown.
- Không có health check = platform không phân biệt được "app bị treo" vs "app đang xử lý request chậm".

### Exercise 1.3: Graceful shutdown là gì và tại sao cần?

Khi platform gửi SIGTERM (trước khi kill container):
1. App ngừng nhận request mới
2. Đợi các request đang xử lý hoàn thành (timeout 30s)
3. Đóng connection (DB, Redis)
4. Thoát sạch

Không có graceful shutdown → request đang chạy bị cắt giữa chừng → user nhận 502, data bị corrupt.

---

## Part 2: Docker

### Exercise 2.1: Single-stage vs Multi-stage — khác gì?

| | Single-stage | Multi-stage |
|---|---|---|
| Image size | ~1 GB (full Python + gcc + headers) | ~200 MB (chỉ slim + packages) |
| Security | Chứa compiler, debug tools → bề mặt tấn công lớn | Chỉ runtime, không có build tools |
| Build time | Nhanh hơn lần đầu | Chậm hơn chút, nhưng cache tốt |
| Dùng khi | Develop/debug local | Production deployment |

### Exercise 2.2: Tại sao cần non-root user?

Nếu app chạy root trong container và bị exploit (RCE qua input injection), attacker có quyền root:
- Đọc mọi file (secrets, certificates)
- Cài thêm malware
- Escape container (trong một số cấu hình)

Với non-root user: dù bị RCE, attacker chỉ có quyền user thường → không install package, không đọc `/etc/shadow`.

### Exercise 2.3: `COPY requirements.txt` trước `COPY . .` — tại sao?

Docker cache layer theo thứ tự. Nếu `requirements.txt` không đổi → layer `RUN pip install` được cache → rebuild chỉ mất vài giây (chỉ copy code mới). Nếu `COPY . .` trước → bất kỳ thay đổi code nào cũng invalidate cache → phải pip install lại (2-5 phút).

---

## Part 3: Cloud Deployment

### Exercise 3.1: So sánh 3 platform

| Tiêu chí | Railway | Render | Cloud Run |
|----------|---------|--------|-----------|
| Setup time | 5 phút | 10 phút | 30 phút |
| Free tier | $5/month credit | 750h/month | 2M requests free |
| Auto-scale | ❌ (fixed instances) | ❌ (manual) | ✅ (0→N instances) |
| Kiểm soát | Thấp (PaaS) | Trung bình | Cao (serverless container) |
| CI/CD | Auto từ GitHub | Auto từ GitHub | Cloud Build pipeline |
| Phù hợp | Demo, MVP nhanh | Side project | Production thật |

### Exercise 3.2: Tại sao Cloud Run tính tiền theo request?

Cloud Run scale từ 0 instance khi không có traffic → không tốn tiền idle. Khi request đến:
1. Cold start: khởi động container (~2-5s)
2. Xử lý request
3. Sau vài phút idle → scale về 0

Mô hình này lý tưởng cho AI agent vì: traffic thường rất bursty (có lúc dùng, có lúc không), cost = $0 khi không ai dùng.

### Exercise 3.3: `$PORT` environment variable

Cloud platform tự chọn port cho mỗi container (không phải luôn 8000). App phải đọc `PORT` từ env:
```python
port = int(os.getenv("PORT", 8000))
```
Hardcode port = deploy lên Railway/Cloud Run sẽ fail.

---

## Part 4: API Security

### Exercise 4.1: 3 lớp bảo vệ cần thiết cho public AI API

1. **Authentication (API Key/JWT)** — Xác định *ai* đang gọi. Ngăn anonymous access.
2. **Rate Limiting** — Giới hạn *bao nhiêu* request/phút. Ngăn spam/DDoS.
3. **Cost Guard** — Giới hạn *bao nhiêu tiền*/ngày. Ngăn bill shock khi bị abuse.

### Exercise 4.2: Sliding window rate limit hoạt động thế nào?

```
Timeline:   |----60s window----|
Requests:   [t1] [t2] ... [t20] [t21] ← REJECT (429)

Khi t1 hết hạn (> 60s trước):
            [t2] ... [t20] [t21]  ← chỉ còn 20, nhận thêm được
```

Dùng `deque` để lưu timestamp. Mỗi request mới:
1. Xoá các timestamp cũ hơn 60s
2. Đếm còn bao nhiêu → nếu >= limit → reject 429
3. Append timestamp mới

### Exercise 4.3: Tại sao cost guard quan trọng hơn rate limit với AI app?

- 1 request GPT-4 có thể tốn $0.03-0.12 (với context dài: $1+)
- 20 req/phút × 60 phút × 24h = 28,800 requests/ngày
- Nếu mỗi request $0.05 → $1,440/ngày bill shock!
- Rate limit ngăn spam nhưng KHÔNG ngăn "legitimate abuse" (1 user gửi liên tục)
- Cost guard = hard cap: dù rate limit cho phép, hết budget là dừng

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Stateful vs Stateless — vấn đề gì khi scale?

**Stateful (lưu session trong memory):**
```
User A → Instance 1 (memory có history A) ✅
User A → Instance 2 (memory TRỐNG!)       ❌ → mất context
```

Load balancer round-robin không đảm bảo cùng user đến cùng instance. Kết quả: conversation bị "mất trí nhớ" ngẫu nhiên.

**Stateless (lưu session trong Redis):**
```
User A → Instance 1 → đọc Redis → có history ✅
User A → Instance 2 → đọc Redis → có history ✅
```

Mọi instance đều đọc/ghi cùng một Redis → user đến instance nào cũng được.

### Exercise 5.2: Tại sao cần readiness probe khác health probe?

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Mục đích | Container còn sống? | Sẵn sàng nhận traffic? |
| Fail → | Restart container | Ngừng route traffic (không restart) |
| Use case | Detect deadlock, OOM | Đang warm-up, đang graceful shutdown |

Ví dụ: App vừa start, cần 10s load model vào memory. Trong 10s đó:
- `/health` = ok (process còn chạy)
- `/ready` = 503 (chưa load xong model, request sẽ fail)

### Exercise 5.3: Redis TTL và maxmemory-policy

- **TTL (Time To Live)**: Session tự xoá sau 1 giờ không dùng → không leak memory vô hạn
- **`allkeys-lru`**: Khi Redis đầy 128MB → tự xoá key ít dùng nhất (Least Recently Used) → không crash, session cũ mất nhưng app vẫn chạy
