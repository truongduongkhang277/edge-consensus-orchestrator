# Đối chiếu giữa slide và mã nguồn

| Thành phần trong slide | Hiện thực |
|---|---|
| Edge Node | Một tiến trình `RaftNode`, đóng gói bằng container |
| Consensus Module | `begin_election`, `vote`, `append_entries`, `orchestrate` |
| Leader Election | Randomized election timeout, RequestVote và majority vote |
| Distributed Logging | `LogEntry`, AppendEntries, commit index, lưu JSON bền vững |
| Resource Monitor | Load trung bình và dung lượng đĩa khả dụng trong `/status` |
| Deployment Manager | State machine xử lý DEPLOY/MIGRATE/REPLICATE/REMOVE |
| Docker/Kubernetes Runtime | Docker Compose triển khai cụm; runtime dịch vụ được mô phỏng an toàn |

## Luồng xử lý một yêu cầu

1. Client gửi lệnh đến một nút bất kỳ.
2. Follower chuyển tiếp đến Leader; nếu chưa có Leader trả `503` để client thử lại.
3. Leader tạo log entry chưa commit.
4. Leader nhân bản toàn bộ log tới các Follower.
5. Khi đủ đa số, Leader đánh dấu commit và áp dụng lệnh vào state machine.
6. Heartbeat kế tiếp truyền `commit_index`, khiến Follower áp dụng cùng quyết định.

## Phạm vi nguyên mẫu

Mã minh họa đúng các khái niệm trọng tâm của đề cương nhưng chưa phải bản Raft dùng cho production. Cơ chế replication hiện gửi toàn bộ log để dễ quan sát; bản hoàn thiện nên dùng `nextIndex/matchIndex`, kiểm tra `prevLogIndex/prevLogTerm`, snapshot và membership change.
