# Khung điều phối phân tán cho cụm Edge

Nguyên mẫu triển khai nội dung trong slide: Raft leader election, heartbeat, distributed log và các lệnh điều phối `DEPLOY`, `MIGRATE`, `REPLICATE`.

## Chạy nhanh bằng Docker

```bash
docker compose up --build
```

Mở bảng điều khiển: http://localhost:8001

Các cổng nút:

- `edge-1`: 8001
- `edge-2`: 8002
- `edge-3`: 8003

## Chạy không cần Docker

Mở ba terminal:

```bash
python -m edge_node --id edge-1 --port 8001 --peers edge-2=http://127.0.0.1:8002,edge-3=http://127.0.0.1:8003
python -m edge_node --id edge-2 --port 8002 --peers edge-1=http://127.0.0.1:8001,edge-3=http://127.0.0.1:8003
python -m edge_node --id edge-3 --port 8003 --peers edge-1=http://127.0.0.1:8001,edge-2=http://127.0.0.1:8002
```

## API demo

Tìm Leader:

```bash
curl http://localhost:8001/status
curl http://localhost:8002/status
curl http://localhost:8003/status
```

Gửi yêu cầu tới bất kỳ nút nào (Follower tự chuyển tiếp tới Leader):

```bash
curl -X POST http://localhost:8002/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"operation":"DEPLOY","service":"patient-api","target":"edge-2","replicas":1}'
```

Di chuyển và nhân bản:

```bash
curl -X POST http://localhost:8001/orchestrate -H "Content-Type: application/json" -d '{"operation":"MIGRATE","service":"patient-api","source":"edge-2","target":"edge-3"}'
curl -X POST http://localhost:8001/orchestrate -H "Content-Type: application/json" -d '{"operation":"REPLICATE","service":"patient-api","target":"edge-1","replicas":2}'
```

Kiểm tra log và trạng thái dịch vụ:

```bash
curl http://localhost:8001/log
curl http://localhost:8001/services
```

## Demo chịu lỗi

1. Xác định nút có `role = leader`.
2. Dừng nút đó, ví dụ `docker compose stop edge-1`.
3. Đợi khoảng 2 giây, kiểm tra hai nút còn lại: một Leader mới sẽ được bầu.
4. Gửi lệnh mới và xác nhận lệnh vẫn được commit với đa số 2/3.
5. Khởi động lại nút cũ: `docker compose start edge-1`; log sẽ được đồng bộ lại khi có lệnh kế tiếp.

> Đây là nguyên mẫu học thuật dùng để minh họa cơ chế. Phần runtime mặc định mô phỏng trạng thái Microservice, không tự ý điều khiển Docker host. Khi triển khai thật cần bổ sung xác thực mTLS, snapshot/compaction, membership change, health-check ứng dụng và adapter Kubernetes/K3s.

## Kiểm thử

```bash
python -m unittest discover -s tests -v
```

