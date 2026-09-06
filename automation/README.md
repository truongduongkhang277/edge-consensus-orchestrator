# AI agent loop

Bộ automation này điều phối một vòng phát triển có kiểm soát trong Git worktree cô lập:

1. DeepSeek phân tích yêu cầu ở chế độ chỉ-đọc.
2. Codex triển khai thay đổi.
3. Các lệnh test trong `policy.json` được chạy trực tiếp, không qua agent.
4. Nếu test lỗi, DeepSeek phân loại lỗi để cung cấp phản hồi cho vòng sau.
5. Claude review độc lập diff và kết quả test.
6. Vòng lặp dừng khi test pass và review chứa `VERDICT: APPROVED`, hoặc khi hết số vòng.

Runner không tự commit, merge, push hay xóa worktree. Sau lần chạy thật, branch, worktree và log được giữ lại để con người kiểm tra. Toàn bộ artifact nằm dưới `.ai-runs/`, đã được bỏ qua bởi Git.

## File

- `run-agent-loop.ps1`: runner, mặc định là dry-run.
- `policy.json`: giới hạn vòng lặp, allowlist/protected paths, cấu hình CLI và test.
- `prompts/`: hợp đồng vai trò cho từng agent.

## Điều kiện

- Chạy từ một Git repository sạch; lần chạy thật từ chối tiếp tục nếu worktree chính có thay đổi.
- Các executable `git`, `python`, `deepseek`, `codex` và `claude` phải có sẵn trong `PATH` khi chạy thật.
- CLI phải nhận prompt qua standard input. Có thể chỉnh tên lệnh/arguments trong `policy.json` theo CLI cục bộ.
- Không đặt token hoặc credential trong policy, prompt hay command line. CLI tự quản lý xác thực bên ngoài repository.
- Xem lại `allowedChangedPaths`, test command và timeout trước mỗi lần chạy thật.

## Dry-run an toàn

Dry-run là mặc định và không tạo thư mục, branch, worktree, không gọi agent, không chạy test:

```powershell
.\automation\run-agent-loop.ps1 -Task "Mô tả thay đổi cần thực hiện"
```

Có thể kiểm tra một policy khác mà vẫn không thực thi:

```powershell
.\automation\run-agent-loop.ps1 -Task "Kiểm tra cấu hình" -PolicyPath .\automation\policy.json -MaxIterations 2
```

## Chạy thật

Chỉ dùng sau khi đã xem dry-run, bảo đảm repository sạch và xác nhận các CLI không tự truy cập mạng trái với chính sách môi trường:

```powershell
.\automation\run-agent-loop.ps1 -Task "Mô tả thay đổi cần thực hiện" -Execute
```

`-Execute` là công tắc duy nhất cho phép tạo `.ai-runs/<run-id>/`, branch và worktree. Runner kiểm tra đường dẫn thay đổi sau mỗi lượt Codex và dừng ngay nếu file nằm ngoài allowlist, chạm protected path hoặc vượt giới hạn số file.

## Artifact

Mỗi lần chạy thật tạo log theo vòng trong `.ai-runs/<run-id>/`, gồm phân tích, output triển khai, log test, triage, review và `summary.md`. Không đưa artifact này vào commit. Việc chấp nhận diff, commit, merge và dọn worktree luôn là thao tác thủ công ngoài runner.

## Tùy chỉnh policy

`policy.json` dùng đường dẫn tương đối với repository. Glob `*` khớp trong một cấp thư mục, còn `**` khớp nhiều cấp. Giữ các cờ `neverCommit`, `neverPush`, `neverMerge` là `true`; runner từ chối chạy thật nếu một trong ba cờ bị tắt.

Nếu CLI cục bộ dùng cú pháp khác, chỉ sửa `command` và `arguments` của agent tương ứng. Không thêm secret vào arguments vì chúng có thể xuất hiện trong log tiến trình hoặc công cụ giám sát hệ thống.
