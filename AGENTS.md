# Quy tắc an toàn cho agent

Các quy tắc này áp dụng cho mọi agent làm việc trong toàn bộ repository này.

1. Chỉ được tạo hoặc sửa file nằm bên trong repository hiện tại.
2. Không được xóa, đổi tên hoặc di chuyển bất kỳ file mã nguồn hiện có nào.
3. Chỉ được xóa file tạm do chính agent tạo trong thư mục `.tmp/`. Không được xóa file khác.
4. Không được sử dụng `git reset --hard`, `git clean`, `git checkout --` hoặc force push dưới mọi hình thức.
5. Không được sửa hoặc hiển thị nội dung của file `.env`, token, mật khẩu, khóa hay bất kỳ thông tin xác thực nào. Nếu gặp dữ liệu nhạy cảm, chỉ báo vị trí và loại rủi ro mà không tiết lộ giá trị.
6. Không được chạy Docker Compose hoặc thực hiện bất kỳ thao tác nào với container nếu chưa có sự chấp thuận rõ ràng của người dùng.
7. Không được truy cập mạng hoặc cài đặt phần mềm/package nếu chưa có sự chấp thuận rõ ràng của người dùng.
8. Trước khi sửa file, phải chạy `git status` và xem xét các thay đổi hiện có để tránh ghi đè công việc của người dùng.
9. Sau khi sửa, phải chạy các kiểm thử liên quan và an toàn. Nếu không thể chạy, phải nêu rõ lý do và phần chưa được kiểm chứng.
10. Khi hoàn thành, phải báo cáo các file đã thay đổi, kết quả kiểm thử và mọi rủi ro còn lại.

