# Đối chiếu với bài báo gốc (FGCS 2026, 108221)

Slide trình bày Raft cải tiến theo chuỗi: đề xuất - bỏ phiếu - chấp thuận - commit - thực thi. Bản mẫu này hiện thực chuỗi đó bằng Leader/Follower, majority quorum và replicated log.

## Những phần đã hiện thực

- Request Handler qua REST API.
- Orchestration Agent xử lý tuần tự từng yêu cầu.
- Consensus với majority `floor(N/2)+1`.
- Leader Election theo term và timeout ngẫu nhiên.
- Distributed Log được nhân bản và lưu bền vững tại từng nút.
- Resource Monitor cung cấp load và dung lượng đĩa.
- State machine mô phỏng deployment, migration và replication.
- Thử nghiệm chịu lỗi bằng cách dừng Leader và quan sát bầu Leader mới.

## Khác biệt cần nêu khi bảo vệ

Bài báo gốc gắn leadership với từng đợt yêu cầu: khi xử lý xong, Leader hết vai trò và hệ thống về trạng thái Pause; vì vậy không cần heartbeat duy trì Leader. Khi có nhiều ứng viên, độ ưu tiên dựa trên số yêu cầu chờ, cộng bộ đếm aging để tránh starvation; nếu bằng nhau thì ưu tiên yêu cầu cũ hơn.

Slide 20 lại mô tả Leader duy trì bằng heartbeat và bầu lại khi mất heartbeat. Bản mẫu ưu tiên khớp với slide, vì vậy dùng Leader ổn định kiểu Raft. Khi viết báo cáo triển khai, nên gọi đây là **biến thể minh họa theo nội dung slide**, không tuyên bố là bản sao mã nguồn thực nghiệm của tác giả.

Bài báo cũng lựa chọn nút triển khai bằng cách tối thiểu hóa:

`U_i = (R_cpu + W_i,cpu)/C_i,cpu + (R_ram + W_i,ram)/C_i,ram`

Trong bản mẫu, `target` được client chỉ định để người xem chủ động trình diễn migration/replication. Phiên bản nghiên cứu tiếp theo nên bổ sung lựa chọn tự động theo `U_i`, hàng đợi bất đồng bộ, GlusterFS và Docker Engine adapter.

## Kịch bản đánh giá đề xuất

| Thí nghiệm | Biến đo |
|---|---|
| Gửi 100 lệnh tuần tự | Thời gian phản hồi trung bình, p95, tỷ lệ commit |
| Dừng một Follower | Tỷ lệ commit còn lại, độ nhất quán log |
| Dừng Leader | Thời gian bầu Leader mới, thời gian gián đoạn |
| Tăng từ 3 lên 5 nút | Độ trễ consensus theo kích thước cụm |
| Tạo tải CPU/RAM khác nhau | Độ đúng của quyết định chọn nút (ở phiên bản tự động) |

