# Ma trận khoảng cách tái hiện bài báo

Ma trận này đối chiếu yêu cầu của bài báo với hành vi đang có trong repository.
`PASS` chỉ có nghĩa là hành vi hiện có được kiểm chứng; không có nghĩa là toàn
bộ hệ thống đã tái hiện bài báo. Các mục chưa có implementation được đánh dấu
`MISSING` và characterization test tương ứng dùng `skip` hoặc `expectedFailure`.

| # | Paper requirement | Current module | Evidence/test | Current status | Missing behavior | Acceptance criterion |
|---:|---|---|---|---|---|---|
| 1 | Cụm gồm sáu logical nodes, có thể xác định quorum theo toàn bộ cấu hình. | `edge_node/application/consensus.py` (`RaftNode.majority`, `status`) | `test_six_logical_nodes_are_reflected_in_status_and_quorum` | `PARTIAL` | Có thể tạo cấu hình sáu node bằng peer map, nhưng chưa có test/integration run sáu tiến trình thực sự. | Sáu node được khởi động trong một run, mọi node báo cùng `configured_nodes=6`, election/commit đúng quorum 4 và log hội tụ. |
| 2 | Mỗi orchestration request có một temporary leader; xử lý xong leader trở về Pause/không duy trì leadership. | `edge_node/application/consensus.py` (`orchestrate`, election loop) | `test_leader_is_temporary_per_request` (`expectedFailure`) | `MISSING` | Leader hiện giữ role `leader` sau commit và tiếp tục heartbeat; không có Pause hay leader lifecycle theo request. | Sau mỗi request hoàn tất, role chuyển về Pause/follower theo paper; request kế tiếp có thể bầu temporary leader mới. |
| 3 | Khi có nhiều candidate, chọn theo priority + aging, hòa thì theo timestamp cũ hơn. | `edge_node/application/request_queue.py`, `request_service.py`, `domain/request.py` hiện là placeholder; `consensus.py` chỉ serializes bằng lock | `test_priority_aging_and_timestamp_for_multiple_candidates` (`skip`, lý do MISSING) | `MISSING` | Không có request model/queue, priority, aging counter hoặc timestamp tie-breaker. `orchestration_lock` chỉ tuần tự hóa, không xếp hạng request. | Với nhiều request chờ, thứ tự quan sát được đúng priority; aging tăng theo thời gian chờ và timestamp phá hòa ổn định. |
| 4 | Chỉ strict majority mới commit/deploy; mất quorum thì không deploy. | `edge_node/application/consensus.py` (`majority`, `_replicate_proposal`, `orchestrate`) | `test_loss_of_quorum_does_not_commit_or_deploy` | `PASS` | Chưa có multi-process fault experiment trong test này; kiểm chứng dùng peer acknowledgements giả lập và không chạy Docker. | Khi acknowledgements < `floor(N/2)+1`, proposal bị rollback, `commit_index`/desired state không đổi và reconciler không được gọi. |
| 5 | Placement tối thiểu expected CPU/RAM utilization: `U_i = (R_cpu+W_i,cpu)/C_i,cpu + (R_ram+W_i,ram)/C_i,ram`. | `edge_node/domain/scheduler.py` (`ResourceScheduler`), `consensus.py` (`AUTO`) | `test_scheduler_ranks_multiple_candidates_by_current_weighted_score` | `PARTIAL` | Có ranking AUTO theo score trọng số CPU 0.5, RAM 0.3, replica 0.2; chưa có capacity/request weights và chưa chứng minh đúng công thức `U_i`. | AUTO phải chọn candidate có `U_i` thấp nhất với nhiều candidate, và ghi rõ input capacity/workload để tái lập quyết định. |
| 6 | Distributed log phải hoàn tất commit trước deployment/execution. | `edge_node/application/consensus.py`, `application/container_reconciler.py` | `test_commit_state_precedes_reconcile_request` | `PASS` | Chưa kiểm chứng engine/container thật theo quy định không dùng Docker. | Mọi reconcile/deployment callback chỉ được phát sau `commit_index` và `last_applied` đã cập nhật; lỗi/mất quorum không gọi callback. |
| 7 | Section 8 phải báo cáo tám metric cần thiết cho mỗi orchestration. | `edge_node/application/consensus.py` (`phase_metrics`, `gateway_metrics`), `application/events.py` | `test_successful_orchestration_exposes_eight_section8_metrics` | `PARTIAL` | Hiện có tám trường đo timing/counter (`schedule_ms`, `proposal_persist_ms`, `replication_ms`, `commit_persist_ms`, `heartbeat_ms`, `full_sync_fallbacks`, `queue_wait_ms`, `total_ms`), nhưng chưa có mapping chính thức tới định nghĩa Section 8 và chưa export bộ metric thí nghiệm hoàn chỉnh. | Tài liệu Section 8 định nghĩa từng metric, đơn vị và điểm đo; API/export trả đủ tám metric nhất quán cho success và failure. |
| 8 | Đánh giá tải 0.5–3 request/giây và báo cáo CI 95% (cùng success/latency/p95). | `edge_node/scripts/load_test.py`, `scripts/run_experiments.py` | `test_load_experiment_defaults_cover_requested_rates_and_ci95_is_computable`; bài chạy tải thật được đánh dấu skip | `PARTIAL` | Có harness và hàm percentile/CI95, nhưng chưa chạy trong characterization test vì cần các gateway đang phục vụ; không có bằng chứng kết quả 0.5–3 RPS trong test cục bộ này. | Chạy lặp các rate 0.5, 1, 1.5, 2, 2.5, 3 RPS trên sáu node, lưu mean/p95/success và CI95, kèm artifact và cấu hình run. |

## Quy ước bằng chứng

- Test characterization không sửa production code và không khởi động Docker,
  network hay container.
- `expectedFailure` ghi nhận một assertion về hành vi bài báo mà implementation
  hiện tại chưa đáp ứng; `skip` dùng cho capability chưa tồn tại hoặc yêu cầu
  môi trường ngoài phạm vi test cục bộ.
- Các kết quả tải và CI95 chỉ được coi là bằng chứng tái hiện sau khi chạy
  harness với gateway/node thật; việc có code harness không tự động là PASS.
