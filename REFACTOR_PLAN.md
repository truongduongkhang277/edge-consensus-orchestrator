# Kế hoạch Refactor theo từng bước nhỏ

Tài liệu này chỉ là kế hoạch. **Chưa triển khai commit nào** dưới đây.
Đây là tệp tài liệu duy nhất được tạo trong phạm vi công việc này; không sửa production code, không xóa tệp.

## 1. Mục đích

Giảm kích thước và gỡ trách nhiệm chồng chéo đã khảo sát trong `edge_node/application/consensus.py` (~1800 dòng, `RaftNode`) và vùng `presentation/`, bằng các commit nhỏ, độc lập, giữ nguyên hành vi bên ngoài (API HTTP, định dạng log JSON, dashboard). Mỗi bước luôn kèm tệp ảnh hưởng, rủi ro và kiểm thử cần chạy.

## 2. Nguyên tắc & giới hạn (non-goals — bắt buộc tuân thủ)

1. **Chỉ tạo/cập nhật tài liệu** (`REFACTOR_PLAN.md`). Không sửa production code. Không xóa tệp. (Phạm vi commit của kế hoạch này sẽ được phê duyệt riêng trước khi thực thi.)
2. **Không gộp** `edge_node/config/services.json` và `edge_node/config/deployments.json` — giữ nguyên cả hai.
3. **Không tạo `peer_rpc.py`** và **không gom fan-out** (`ThreadPoolExecutor`/`as_completed`) ở giai đoạn đầu. Việc gom fan-out chung nếu cần nằm ngoài kế hoạch này.
4. **Không dùng cờ `skip_revalidate`**: `apply` và `rebuild` log **vẫn phải validate** dữ liệu log.
5. **Không thay đổi cách tính majority theo số node online**: `majority` vẫn tính theo số node *cấu hình* `(len(peers) + 1) // 2 + 1` (`configured_nodes`), không theo node đang online.
6. **Dynamic membership nằm ngoài phạm vi** refactor này.
7. **Giữ nguyên public API của `RaftNode`**: `start`, `stop`, `status`, `runtime_status`, `orchestrate`, `vote`, `append_entries`, `services`, `events`.
8. Các module nghiệp vụ `scripts/fault_test.py` và `scripts/export_metrics.py` được **giữ lại** (cần cho thực nghiệm bài báo), dù hiện rỗng.
9. Không vừa di chuyển test vừa thay đổi production logic trong cùng một commit.

## 3. Tóm tắt trạng thái hiện tại (đã khảo sát, chỉ đọc)

- `edge_node/application/consensus.py`: `RaftNode` gộp Raft protocol + orchestration + lập lịch AUTO + reconcile Docker + xuất trạng thái web.
- Validate/normalize lệnh bị nhân đôi (`_validate_command` ~1509 song song `ServiceStateMachine.validate`; `VALID_OPERATIONS` trùng giữa `RaftNode` và `ServiceStateMachine`).
- `presentation/dashboard.py`: dashboard là chuỗi HTML/CSS/JS nhúng (~1300 dòng) trong Python.
- `presentation/http_server.py`: handler chọc trực tiếp `node.lock` / `node.log` / `node.services` / `node.events`.
- Một số module 0 byte (placeholder): `application/{metrics,request_queue,request_service}.py`, `domain/{request,service_profile}.py`.
- Hai gốc test: `tests/` (cấp gốc) và `edge_node/tests/`.

## 4. Kế hoạch commit (thứ tự bắt buộc)

Quy ước kiểm thử chung sau mỗi commit thay đổi logic:
`python -m unittest discover -s edge_node/tests -v` và `python -m unittest discover -s tests -v`.

---

### Commit 1 — `docs: add staged refactoring plan`
- **Mô tả:** Chỉ thêm `REFACTOR_PLAN.md`.
- **Tệp ảnh hưởng:** `REFACTOR_PLAN.md` (mới).
- **Rủi ro:** Không.
- **Kiểm thử:** Không (tài liệu).

---

### Commit 2 — `test: characterize current HTTP and Raft contracts`
- **Mô tả:** Thêm characterization test ghi lại hành vi *hiện tại*, **không sửa production code**.
  - Bao phủ `majority` cho **1, 3, 5, 10 và 12** node.
  - Bao phủ `status`, `vote`, `append_entries`, `orchestrate` và các HTTP status (201/400/503 v.v.).
- **Tệp ảnh hưởng:** thêm test mới (khuyến nghị `edge_node/tests/test_contracts.py`, có thể cả tệp hỗ trợ `helpers`); production code không đổi.
- **Rủi ro:** Rất thấp (test-only). Mục tiêu là "lưới an toàn" để các commit refactor sau chạy lại.
- **Kiểm thử:** chạy chính bộ test mới + hai suite hiện có.

---

### Commit 3 — `ci: run compile and unit tests on push`
- **Mô tả:** Thêm GitHub Actions chạy kiểm tra cú pháp/biên dịch (`compileall`/`py_compile`) và **cả hai** suite unit test (`tests/` và `edge_node/tests/`) khi `push`.
- **Tệp ảnh hưởng:** `.github/workflows/ci.yml` (mới).
- **Rủi ro:** Rất thấp (infra CI).
- **Kiểm thử:** workflow tự chạy; ngoài ra chạy lại hai suite cục bộ.

---

### Commit 4 — `refactor: extract dashboard static assets`
- **Mô tả:** Tách chuỗi HTML/CSS/JS trong `presentation/dashboard.py` thành asset tĩnh `dashboard.html`, `dashboard.css`, `dashboard.js`. Giữ nguyên route `/` và mọi API HTTP.
- **Tệp ảnh hưởng:** `edge_node/presentation/dashboard.py`, tệp mới (khuyến nghị `edge_node/presentation/static/dashboard.{html,css,js}`), có thể `http_server.py` (phục vụ asset).
- **Rủi ro:** Trung bình — nguy cơ đổi cách phục vụ `/`. Phải đảm bảo nội dung render tương đương và CORS/API không đổi.
- **Kiểm thử:** smoke `GET /` trả HTML; gọi lại `GET /status`, `/services`, `/log`, `/events`, `/runtime`, `POST /orchestrate`, `/raft/vote`, `/raft/append`.

---

### Commit 5 — `refactor: add thread-safe node snapshots`
- **Mô tả:** Thêm các accessor snapshot an toàn luồng trên `RaftNode`: `services_snapshot()`, `log_snapshot()`, `events_snapshot()` (tự lấy `node.lock` bên trong, trả bản sao). **Chưa sửa HTTP server.** Giữ các property `services`/`events` hiện có (public API không đổi).
- **Tệp ảnh hưởng:** `edge_node/application/consensus.py` (chỉ thêm method).
- **Rủi ro:** Thấp (thêm method không đổi hành vi hiện có).
- **Kiểm thử:** characterization test từ Commit 2 + smoke snapshot trả bản sao độc lập.

---

### Commit 6 — `refactor: use public snapshots in HTTP handlers`
- **Mô tả:** `presentation` **không còn truy cập trực tiếp** `node.lock` / `node.log` / `node.services` / `node.events`; thay bằng `services_snapshot()`/`log_snapshot()`/`events_snapshot()`.
- **Tệp ảnh hưởng:** `edge_node/presentation/http_server.py`.
- **Rủi ro:** Trung bình — phải giữ nguyên shape JSON trả về cho từng route.
- **Kiểm thử:** characterization HTTP (Commit 2) + smoke từng `GET`.

---

### Commit 7 — `test: cover command validation and replay`
- **Mô tả:** Bổ sung characterization test cho `validate`, `normalize`, `apply` và `rebuild` **trước khi** thay đổi logic. Ghi rõ hành vi hiện tại (lỗi, thứ tự commit, rebuild từ log).
- **Tệp ảnh hưởng:** thêm test (khuyến nghị `edge_node/tests/test_commands.py`); production code không đổi.
- **Rủi ro:** Rất thấp (test-only).
- **Kiểm thử:** chạy test mới + hai suite.

---

### Commit 8 — `refactor: centralize command normalization`
- **Mô tả:** Tạo `domain/commands.py`; **chỉ hợp nhất** normalize và kiểm tra *cấu trúc* lệnh (field bắt buộc, uppercase/trim, `replicas` int dương, chặn bool, nguồn `source`). `ServiceStateMachine.validate` **vẫn** kiểm tra chuyển trạng thái (trạng thái dịch vụ hiện có). `apply`/`rebuild` **vẫn phải kiểm tra** dữ liệu log (không dùng `skip_revalidate`). `RaftNode._validate_command` và đoạn normalize trong `_orchestrate_serialized` gọi chung module này.
- **Tệp ảnh hưởng:** `edge_node/domain/commands.py` (mới), `edge_node/domain/orchestration.py`, `edge_node/application/consensus.py`.
- **Rủi ro:** Trung bình — phải giữ nguyên thông điệp lỗi và HTTP status (400 vs 503); không đổi luồng validate khi apply/rebuild.
- **Kiểm thử:** test Commit 7 + Commit 2; chạy hai suite.

---

### Commit 9 — `refactor: extract target selection policy`
- **Mô tả:** Di chuyển policy chọn target AUTO/REPLICATE/MIGRATE (loại source khi MIGRATE, ưu tiên node chưa chạy khi REPLICATE) ra khỏi `RaftNode._choose_automatic_target` vào module policy riêng. **Giữ `ResourceScheduler` là domain scoring thuần** (không nhúng policy orchestration).
- **Tệp ảnh hưởng:** module mới (khuyến nghị `edge_node/domain/target_policy.py` hoặc `application/target_selector.py`), `edge_node/application/consensus.py`, `edge_node/domain/scheduler.py` (không đổi logic).
- **Rủi ro:** Trung bình — liên quan dữ liệu cluster (`cluster_statuses`) + `services`.
- **Kiểm thử:** test AUTO chọn đúng node (REPLICATE/MIGRATE/không đủ node→503) + Commit 2/7.

---

### Commit 10 — `refactor: extract runtime reconciliation service`
- **Mô tả:** Tách vòng `_reconcile_loop` và trạng thái `runtime_status` ra một service riêng. `RaftNode` **vẫn giữ `runtime_status`** làm facade và vẫn nối sự kiện `_request_reconcile`/`reconcile_event`.
- **Tệp ảnh hưởng:** module mới (khuyến nghị `edge_node/application/runtime_sync.py`), `edge_node/application/consensus.py`, có thể `infrastructure/container_engine.py` (không đổi interface).
- **Rủi ro:** Cao nhất trong các commit tách — đụng đa luồng (lock, `reconcile_event`, luồng nền).
- **Kiểm thử:** test Commit 2; smoke khi có/không Docker reconciler; kiểm `runtime_status` vẫn phản ánh đúng.

---

### Commit 11 — `test: add multi-node election and fault scenarios`
- **Mô tả:** Thêm test nhiều `RaftNode` trong tiến trình: mất Leader → bầu Leader mới; node kết nối lại; bắt kịp log (catch-up); mất quorum; phục hồi quorum.
- **Tệp ảnh hưởng:** thêm test (khuyến nghị `edge_node/tests/test_multi_node.py`); production code không đổi.
- **Rủi ro:** Rất thấp (test-only), tránh test nhạy timing (dùng timeout ngắn/chủ động).
- **Kiểm thử:** chạy test mới; không làm rung các suite khác.

---

### Commit 12 — `refactor: extract orchestration coordinator`
- **Mô tả:** Tách khâu điều phối: forward follower→leader, gating proposal tuần tự (`orchestration_lock`), commit/rollback, và metric pha ra coordinator riêng. **Giữ `RaftNode.orchestrate` làm facade** (public API không đổi).
- **Tệp ảnh hưởng:** module mới (khuyến nghị `edge_node/application/orchestration_coordinator.py`), `edge_node/application/consensus.py`.
- **Rủi ro:** Cao — động vào luồng lock/rollback nhạy cảm; làm sau các commit 8–10 khi đã có characterization test.
- **Kiểm thử:** Commit 2/7/11; smoke 1 node và cụm (commit đa số, rollback khi thiếu đa số).

---

### Commit 13 — `refactor: extract election behavior`
- **Mô tả:** Chỉ tách hành vi election/vote/chuyển vai trò (`begin_election`, `become_follower`, `vote`) sang module riêng. Không gom fan-out.
- **Tệp ảnh hưởng:** module mới, `edge_node/application/consensus.py`.
- **Rủi ro:** Trung bình–cao — liên quan trạng thái vai trò dùng chung và `_persist`.
- **Kiểm thử:** Commit 2/11.

---

### Commit 14 — `refactor: extract log replication behavior`
- **Mô tả:** Chỉ tách nhân bản log: heartbeat, `AppendEntries`, incremental sync, full-sync fallback và truyền `commit_index`. Không gom fan-out.
- **Tệp ảnh hưởng:** module mới, `edge_node/application/consensus.py`.
- **Rủi ro:** Cao — tách cuối cùng (sau 12–13) để lưới test đã đủ; chú ý `peer_match_index`, rollback suffix xung đột.
- **Kiểm thử:** Commit 2/11; kịch bản catch-up và xung đột log.

---

### Commit 15 — `test: consolidate test suite`
- **Mô tả:** Gộp hai gốc test về một chỗ bằng **`git mv`**. **Không vừa chuyển test vừa thay đổi production logic.**
- **Tệp ảnh hưởng:** di chuyển `tests/test_node.py` (và file liên quan) vào `edge_node/tests/` (hoặc ngược lại theo quyết định); cập nhật đường dẫn discovery.
- **Rủi ro:** Thấp (chỉ di chuyển); giữ nguyên nội dung để không đổi phủ test.
- **Kiểm thử:** chạy lại suite đã hợp nhất + CI.

---

### Commit 16 — `chore: remove confirmed unused placeholders`
- **Mô tả:** Chỉ xóa các module **đã được `rg` xác nhận không bị import**. Giữ nguyên `scripts/fault_test.py` và `scripts/export_metrics.py` (cần cho thực nghiệm bài báo). Không xóa tệp config.
- **Tệp ảnh hưởng:** tiềm năng xóa `edge_node/application/{metrics,request_queue,request_service}.py` và `edge_node/domain/{request,service_profile}.py` — **chỉ sau khi** `rg` chứng minh không có `import` trỏ tới.
- **Rủi ro:** Rất thấp sau bước xác nhận `rg`.
- **Kiểm thử:** grep toàn repo không còn tham chiếu; chạy hai suite.

## 5. Lưu ý xuyên suốt

- Mọi commit tách refactor giữ nguyên **public API** `RaftNode` (mục 2.7) và **không đổi** `majority`/cách đếm `configured_nodes` (mục 2.5).
- Không thực hiện dynamic membership; không gom fan-out HTTP; không `skip_revalidate`; không gộp config service.
- Commit characterization test luôn đứng **trước** commit refactor tương ứng để có lưới an toàn.

## 6. Xác nhận cuối

Toàn bộ commit 1–16 đều **chưa được thực thi**. Cần phê duyệt của người dùng trước khi bắt đầu thực hiện từng commit.
