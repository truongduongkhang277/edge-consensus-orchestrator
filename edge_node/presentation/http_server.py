import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..application.consensus import RaftNode
from .dashboard import DASHBOARD


def make_handler(node: RaftNode):
    """
    Tạo HTTP Handler gắn với một RaftNode cụ thể.
    """

    class EdgeRequestHandler(
        BaseHTTPRequestHandler
    ):
        def log_message(
            self,
            format_string,
            *args
        ):
            """
            Không in các dòng GET/POST thô ra CMD.
            Sự kiện nghiệp vụ đã được EventRecorder ghi.
            """

            return

        def read_json_body(self) -> dict:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            raw_body = self.rfile.read(
                content_length
            )

            if not raw_body:
                return {}

            return json.loads(raw_body)

        def send_json(
            self,
            status_code: int,
            body
        ):
            response_data = json.dumps(
                body,
                ensure_ascii=False
            ).encode("utf-8")

            try:
                self.send_response(status_code)

                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8"
                )

                self.send_header(
                    "Access-Control-Allow-Origin",
                    "*"
                )

                self.send_header(
                    "Content-Length",
                    str(len(response_data))
                )

                self.end_headers()
                self.wfile.write(response_data)

            except (
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError
            ):
                # Trình duyệt đã đóng request.
                pass

        def send_html(
            self,
            html: str
        ):
            response_data = html.encode(
                "utf-8"
            )

            try:
                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(len(response_data))
                )

                self.end_headers()
                self.wfile.write(response_data)

            except (
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError
            ):
                pass

        def do_OPTIONS(self):
            self.send_response(204)

            self.send_header(
                "Access-Control-Allow-Origin",
                "*"
            )

            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type"
            )

            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS"
            )

            self.end_headers()

        # ====================================================
        # GET API
        # ====================================================

        def do_GET(self):
            if self.path == "/":
                self.send_html(DASHBOARD)
                return

            if self.path == "/status":
                self.send_json(
                    200,
                    node.status()
                )
                return

            if self.path == "/services":
                with node.lock:
                    services_snapshot = {
                        service: dict(nodes)
                        for service, nodes
                        in node.services.items()
                    }

                self.send_json(
                    200,
                    services_snapshot
                )
                return

            if self.path == "/runtime":
                self.send_json(
                    200,
                    node.runtime_status()
                )
                return

            if self.path == "/log":
                with node.lock:
                    distributed_log = [
                        asdict(entry)
                        for entry in node.log
                    ]

                self.send_json(
                    200,
                    distributed_log
                )
                return

            if self.path == "/events":
                with node.lock:
                    events_snapshot = list(
                        node.events
                    )

                self.send_json(
                    200,
                    events_snapshot
                )
                return

            self.send_json(
                404,
                {
                    "error": "Không tìm thấy API"
                }
            )

        # ====================================================
        # POST API
        # ====================================================

        def do_POST(self):
            try:
                request_body = (
                    self.read_json_body()
                )

            except (
                ValueError,
                TypeError,
                json.JSONDecodeError
            ):
                self.send_json(
                    400,
                    {
                        "error": "JSON không hợp lệ"
                    }
                )
                return

            if self.path == "/raft/vote":
                result = node.vote(
                    request_body
                )

                self.send_json(
                    200,
                    result
                )
                return

            if self.path == "/raft/append":
                result = node.append_entries(
                    request_body
                )

                self.send_json(
                    200,
                    result
                )
                return

            if self.path == "/orchestrate":
                status_code, result = (
                    node.orchestrate(
                        request_body
                    )
                )

                self.send_json(
                    status_code,
                    result
                )
                return

            self.send_json(
                404,
                {
                    "error": "Không tìm thấy API"
                }
            )

    return EdgeRequestHandler


def create_http_server(
    node: RaftNode,
    host: str,
    port: int
) -> ThreadingHTTPServer:
    """
    Khởi tạo HTTP Server đa luồng cho một Edge Node.

    Cho phép một Follower đồng thời:
    - Chuyển yêu cầu điều phối tới Leader.
    - Nhận log nhân bản ngược lại từ Leader.
    """

    handler = make_handler(node)

    server = ThreadingHTTPServer(
        (host, port),
        handler
    )

    # Các luồng request tự kết thúc khi server dừng.
    server.daemon_threads = True

    return server