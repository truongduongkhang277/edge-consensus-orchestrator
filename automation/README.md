# AI agent loop

Bộ automation này điều phối một vòng phát triển có kiểm soát trong Git worktree cô lập:

1. DeepSeek phân tích yêu cầu ở chế độ chỉ-đọc.
2. Codex triển khai thay đổi.
3. Các lệnh test trong `policy.json` được chạy trực tiếp, không qua agent.
4. Nếu test lỗi, DeepSeek phân loại lỗi để cung cấp phản hồi cho vòng sau.
5. Claude review độc lập diff và kết quả test.
6. Vòng lặp dừng khi test pass và review chứa `VERDICT: APPROVED`, hoặc khi hết số vòng.

Runner không tự commit, merge, push hay xóa worktree. Sau lần chạy thật, branch, worktree và log được giữ lại để con người kiểm tra. Toàn bộ artifact nằm dưới `.ai-runs/`, đã được bỏ qua bởi Git.

## Mô hình an toàn

Không chạy `-Execute` trên repository có file chưa commit. Worktree cô lập là lớp bảo vệ chính: mọi thay đổi của Codex phải nằm trong worktree riêng và worktree được giữ lại khi có vi phạm để điều tra.

Các lớp bổ sung gồm:

1. Codex chạy với `workspace-write`; việc hạn chế mạng của môi trường chạy là lớp thứ hai. Runner không tự nhận rằng CLI đã bị chặn mạng, vì vậy người vận hành vẫn phải cấu hình và xác minh network restriction bên ngoài script.
2. Runner resolve đường dẫn tuyệt đối của `git.exe`, đặt `git.cmd`/`git.ps1` guard ở đầu `PATH` của Codex, đồng thời đặt `GIT_TERMINAL_PROMPT=0` và `GCM_INTERACTIVE=Never`.
3. Git guard chỉ cho phép `status`, `diff`, `ls-files`, `log`, `show`, `rev-parse` và `grep`. `forbiddenGitArguments` trong policy được nạp vào guard và kiểm tra khi chạy.
4. Trước các agent stage, runner ghi `git-baseline.json`. Sau mỗi stage, runner so sánh HEAD, branch và status của repository chính/worktree, rồi kiểm tra file xóa, allowlist, protected paths, số file và số dòng diff.

Git wrapper không phải sandbox tuyệt đối: tiến trình có thể cố gọi thẳng một executable khác hoặc sửa metadata bằng cơ chế ngoài wrapper. Vì vậy wrapper và kiểm tra HEAD/status chỉ là lớp phòng vệ/phát hiện bổ sung, không thay thế worktree cô lập, `workspace-write`, network restriction và review của con người.

## File

- `run-agent-loop.ps1`: runner, mặc định là dry-run.
- `policy.json`: giới hạn vòng lặp, allowlist/protected paths, cấu hình CLI và test.
- `prompts/`: hợp đồng vai trò cho từng agent.
- `tests/run-agent-loop.internal.tests.ps1`: test mock cho Git guard, invariant và Claude gate; không tạo worktree.

## Điều kiện

- Chạy từ một Git repository sạch; lần chạy thật từ chối tiếp tục nếu worktree chính có thay đổi.
- Các executable `git`, `python`, `deepseek`, `codex` và `claude` phải có sẵn trong `PATH` khi chạy thật.
- CLI phải nhận prompt qua standard input. Có thể chỉnh tên lệnh/arguments trong `policy.json` theo CLI cục bộ.
- Không đặt token hoặc credential trong policy, prompt hay command line. CLI tự quản lý xác thực bên ngoài repository.
- Xem lại `allowedChangedPaths`, test command và timeout trước mỗi lần chạy thật.

## Dry-run an toàn

Dry-run là mặc định và không tạo thư mục, branch, worktree, không gọi agent, không chạy test:

```powershell
.\automation\run-agent-loop.ps1 -Requirement "Chỉ đọc README.md" -MaxIterations 1
```

Nếu bỏ `-MaxIterations`, runner dùng `execution.maxIterations` từ `policy.json`. Tham số dòng lệnh chỉ được phép giảm số vòng, không được vượt giới hạn policy hoặc giới hạn cứng 2 vòng:

```powershell
.\automation\run-agent-loop.ps1 -Requirement "Kiểm tra cấu hình"
```

Có thể chọn thư mục gốc cho artifact/worktree bên trong repository; dry-run dưới đây chỉ hiển thị kế hoạch:

```powershell
.\automation\run-agent-loop.ps1 -Requirement "Kiểm tra cấu hình" -WorktreeRoot .\.ai-runs
```

## Chạy thật

Chỉ dùng sau khi đã xem dry-run, bảo đảm repository sạch và xác nhận các CLI không tự truy cập mạng trái với chính sách môi trường:

```powershell
.\automation\run-agent-loop.ps1 -Requirement "Mô tả thay đổi cần thực hiện" -Execute
```

Giao diện script gồm đúng bốn tham số nghiệp vụ: `-Requirement` (bắt buộc), `-MaxIterations`, `-Execute` và `-WorktreeRoot`. `Requirement` được đưa vào prompt qua dữ liệu/standard input, không được ghép thành lệnh shell.

`-Execute` là công tắc duy nhất cho phép tạo `<WorktreeRoot>/<run-id>/`, branch và worktree. Nếu không chỉ định `-WorktreeRoot`, giá trị mặc định lấy từ `execution.runDirectory` trong policy (`.ai-runs`). Runner kiểm tra đường dẫn thay đổi sau mỗi lượt Codex và dừng ngay nếu file nằm ngoài allowlist, chạm protected path hoặc vượt giới hạn số file. `WorktreeRoot` phải nằm bên trong repository.

## Cổng test và review

Policy cấu hình đúng hai bộ test. Claude chỉ được gọi tối đa một lần và chỉ sau khi cả hai test exit code `0`, `git diff --check` đạt, policy đạt, không có file xóa, HEAD/branch không đổi và repository chính vẫn sạch.

Nếu test lỗi, runner gọi DeepSeek triage và chuyển kết quả cho vòng Codex kế tiếp; Claude không được gọi. Nếu hết tối đa hai vòng mà test vẫn lỗi, summary có trạng thái `TEST_FAILED`. Runner không commit, push, merge, xóa hoặc tự dọn worktree.

Các giới hạn bắt buộc được runner xác minh trước khi chạy thật: `maxIterations <= 2`, `maxClaudeCalls = 1`, `maxChangedFiles <= 20` và `maxDiffLines <= 1000`.

Chạy test nội bộ không cần agent/API hay worktree:

```powershell
.\automation\tests\run-agent-loop.internal.tests.ps1
```

## Artifact

Mỗi lần chạy thật tạo log theo vòng trong `.ai-runs/<run-id>/`, gồm phân tích, output triển khai, log test, triage, review và `summary.md`. Không đưa artifact này vào commit. Việc chấp nhận diff, commit, merge và dọn worktree luôn là thao tác thủ công ngoài runner.

## Tùy chỉnh policy

`policy.json` dùng đường dẫn tương đối với repository. Glob `*` khớp trong một cấp thư mục, còn `**` khớp nhiều cấp. Giữ các cờ `neverCommit`, `neverPush`, `neverMerge` là `true`; runner từ chối chạy thật nếu một trong ba cờ bị tắt.

Nếu CLI cục bộ dùng cú pháp khác, chỉ sửa `command` và `arguments` của agent tương ứng. Không thêm secret vào arguments vì chúng có thể xuất hiện trong log tiến trình hoặc công cụ giám sát hệ thống.
