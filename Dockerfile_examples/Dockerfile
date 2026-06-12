# ==========================================
# STAGE 1: The Build Environment
# ==========================================
# We use a large image that includes the Go compiler and tools
FROM golang:1.22 AS builder

WORKDIR /app

# Copy the rest of the source code
COPY . .

# Compile the application into a single, statically-linked binary named "myapp"
RUN CGO_ENABLED=0 go build -o myapp .

# ==========================================
# STAGE 2: The Production Environment
# ==========================================
# We switch to a completely fresh, microscopic image for production
FROM alpine:3.19

WORKDIR /app

# Tạo non-root user
RUN addgroup -S appuser && adduser -S appuser -G appuser

# Đặt ownership cho appuser
RUN chown -R appuser:appuser /app

# Chuyển sang non-root user
USER appuser

# CRITICAL STEP: Copy ONLY the compiled binary from the 'builder' stage
COPY --from=builder /app/myapp .

# Expose port and define the command to run the app
EXPOSE 8080
CMD ["./myapp"]