from __future__ import annotations

import copy
import random
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from ..domain.models import LogEntry
from ..domain.orchestration import ServiceStateMachine
from ..domain.scheduler import ResourceScheduler
from ..infrastructure.http_client import request_json
from ..infrastructure.json_repository import JsonStateRepository
from ..infrastructure.resource_monitor import ResourceMonitor
from .container_reconciler import ContainerReconciler
from .events import EventRecorder


class RaftNode:
    """
    Xử lý Leader Election, bỏ phiếu, heartbeat,
    nhân bản log và commit lệnh điều phối.
    """

    VALID_OPERATIONS = {
        "DEPLOY",
        "MIGRATE",
        "REPLICATE",
        "REMOVE"
    }

    HEARTBEAT_INTERVAL_SECONDS = 0.5
    ELECTION_TIMEOUT_MIN_SECONDS = 4.0
    ELECTION_TIMEOUT_MAX_SECONDS = 7.0
    PEER_REQUEST_TIMEOUT_SECONDS = 0.8

    def __init__(
        self,
        node_id: str,
        peers: dict[str, str],
        data_dir: str,
        container_reconciler: (
            ContainerReconciler | None
        ) = None
    ):
        self.id = node_id
        self.peers = peers
        self.lock = threading.RLock()
        # Mỗi node chỉ xử lý một proposal orchestration tại một thời điểm.
        # HTTP server vẫn có thể phục vụ các API đọc song song.
        self.orchestration_lock = threading.Lock()
        self.heartbeat_lock = threading.Lock()

        self.role = "follower"
        self.term = 0
        self.voted_for: str | None = None
        self.leader_id: str | None = None

        self.log: list[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0

        # Theo dõi mức đồng bộ của từng Follower. Cơ chế hiện tại vẫn
        # có full-sync dự phòng, nhưng đường chạy bình thường chỉ gửi
        # entry mới thay vì truyền lại toàn bộ distributed log.
        self.peer_match_index: dict[str, int] = {
            peer_id: 0
            for peer_id in self.peers
        }

        self._last_orchestration_metrics: dict[str, float] = {}
        self._last_replication_fallbacks = 0

        self.last_heartbeat = time.monotonic()
        self.election_timeout = self._new_timeout()
        self.running = True

        self.repository = JsonStateRepository(
            data_dir=data_dir,
            node_id=node_id
        )

        self.state_machine = ServiceStateMachine()

        self.event_recorder = EventRecorder(
            node_id=node_id,
            lock=self.lock
        )

        self.container_reconciler = (
            container_reconciler
        )

        self.reconcile_event = threading.Event()

        self._runtime_status = {
            "enabled": (
                container_reconciler is not None
            ),
            "node_id": self.id,
            "status": (
                "pending"
                if container_reconciler
                else "disabled"
            ),
            "services": [],
            "containers": []
        }

        self._load_state()

        self.event(
            "NODE_START",
            (
                f"Khởi động nút {self.id}; "
                f"kết nối {len(self.peers)} nút ngang hàng"
            )
        )

    @property
    def services(self):
        return self.state_machine.services

    @property
    def events(self):
        return self.event_recorder.items

    @property
    def majority(self):
        """
        Số phiếu tối thiểu cần để commit.
        Cụm 3 nút cần ít nhất 2 phiếu.
        """

        return (len(self.peers) + 1) // 2 + 1

    @classmethod
    def _new_timeout(cls):
        return random.uniform(
            cls.ELECTION_TIMEOUT_MIN_SECONDS,
            cls.ELECTION_TIMEOUT_MAX_SECONDS
        )

    def event(
        self,
        kind: str,
        message: str,
        **details
    ):
        self.event_recorder.record(
            kind,
            message,
            **details
        )

    # ========================================================
    # LƯU VÀ KHÔI PHỤC TRẠNG THÁI
    # ========================================================

    def _load_state(self):
        state = self.repository.load()

        self.term = state.get("term", 0)
        self.voted_for = state.get("voted_for")

        self.log = [
            LogEntry(**item)
            for item in state.get("log", [])
        ]

        self.commit_index = state.get(
            "commit_index",
            0
        )

        # Không tin tuyệt đối dữ liệu persisted. commit_index phải luôn
        # nằm trong giới hạn của log.
        self.commit_index = max(
            0,
            min(int(self.commit_index), len(self.log))
        )

        for index, entry in enumerate(
            self.log,
            start=1
        ):
            entry.committed = (
                index <= self.commit_index
            )

        self.state_machine.rebuild(self.log)
        self.last_applied = self.commit_index

    def _persist(self):
        self.repository.save(
            term=self.term,
            voted_for=self.voted_for,
            commit_index=self.commit_index,
            log=self.log
        )

    def _apply(self, command: dict):
        """
        Giữ tương thích với code và kiểm thử cũ.
        """

        self.state_machine.apply(command)

    def _apply_committed_entries(self):
        """
        Áp dụng tuần tự mọi entry từ last_applied đến commit_index.

        Nhờ đó, nếu một entry cũ chưa commit được nhưng sau đó nằm
        trong một prefix đã đạt đa số, Leader và Follower vẫn áp dụng
        cùng một chuỗi lệnh theo cùng thứ tự.
        """

        while self.last_applied < self.commit_index:
            next_index = self.last_applied + 1
            entry = self.log[next_index - 1]

            entry.committed = True
            self.state_machine.apply(entry.command)
            self.last_applied = next_index

    def _rebuild_services(self):
        self.state_machine.rebuild(self.log)
        self.last_applied = self.commit_index

    def _request_reconcile(self):
        """
        Đánh thức luồng đồng bộ container.
        Không thực hiện Docker ngay trong Raft lock.
        """

        if self.container_reconciler:
            self.reconcile_event.set()

    def _services_snapshot(self) -> dict:
        with self.lock:
            return {
                service: dict(nodes)
                for service, nodes
                in self.services.items()
            }

    def _reconcile_loop(self):
        """
        Luồng nền đồng bộ desired state với Docker.

        Ngoài việc được đánh thức khi có commit,
        luồng còn kiểm tra lại sau mỗi 5 giây để
        tự khôi phục container bị dừng hoặc bị xóa.
        """

        while self.running:
            requested = self.reconcile_event.wait(
                timeout=5.0
            )

            self.reconcile_event.clear()

            if not self.running:
                break

            if not self.container_reconciler:
                continue

            desired_services = (
                self._services_snapshot()
            )

            try:
                result = (
                    self.container_reconciler
                    .reconcile(desired_services)
                )

                service_results = result.get(
                    "services",
                    []
                )

                degraded = any(
                    service.get("status")
                    in {"failed", "degraded"}
                    for service in service_results
                )

                runtime_state = {
                    **result,
                    "enabled": True,
                    "status": (
                        "degraded"
                        if degraded
                        else "ready"
                    ),
                    "updated_at": time.time()
                }

                running_count = sum(
                    1
                    for container
                    in result.get(
                        "containers",
                        []
                    )
                    if (
                        container.get("status")
                        == "running"
                    )
                )

                with self.lock:
                    previous_status = (
                        self._runtime_status.get(
                            "status"
                        )
                    )

                    self._runtime_status = (
                        runtime_state
                    )

                if (
                    requested
                    or previous_status
                    != runtime_state["status"]
                ):
                    self.event(
                        "CONTAINER_SYNC",
                        (
                            f"Đồng bộ Docker tại "
                            f"{self.id}: "
                            f"{running_count} container "
                            f"đang chạy"
                        ),
                        running_containers=(
                            running_count
                        )
                    )

            except Exception as error:
                error_message = str(error)

                with self.lock:
                    previous_error = (
                        self._runtime_status.get(
                            "error"
                        )
                    )

                    self._runtime_status = {
                        "enabled": True,
                        "node_id": self.id,
                        "status": "failed",
                        "error": error_message,
                        "services": [],
                        "containers": [],
                        "updated_at": time.time()
                    }

                if (
                    requested
                    or previous_error
                    != error_message
                ):
                    self.event(
                        "CONTAINER_FAILED",
                        (
                            "Không thể đồng bộ Docker "
                            f"tại {self.id}: "
                            f"{error_message}"
                        )
                    )

    def runtime_status(self) -> dict:
        """
        Trả về actual state của Docker.
        """

        with self.lock:
            return copy.deepcopy(
                self._runtime_status
            )

    # ========================================================
    # KHỞI ĐỘNG VÀ VÒNG LẶP BẦU CỬ
    # ========================================================

    def start(self):
        election_thread = threading.Thread(
            target=self._election_loop,
            daemon=True,
            name=f"election-{self.id}"
        )

        election_thread.start()

        if self.container_reconciler:
            reconcile_thread = threading.Thread(
                target=self._reconcile_loop,
                daemon=True,
                name=f"reconcile-{self.id}"
            )

            reconcile_thread.start()

            # Đồng bộ trạng thái đã phục hồi từ log.
            self._request_reconcile()

    def stop(self):
        self.running = False

        # Đánh thức luồng đang chờ để nó kết thúc.
        self.reconcile_event.set()

    def _election_loop(self):
        while self.running:
            time.sleep(0.1)

            with self.lock:
                role = self.role

                expired = (
                    time.monotonic()
                    - self.last_heartbeat
                    > self.election_timeout
                )

            if role == "leader":
                self.send_heartbeats()
                time.sleep(
                    self.HEARTBEAT_INTERVAL_SECONDS
                )

            # Leader chỉ tồn tại trong thời gian xử lý một orchestration
            # request. Không tự bầu leader khi hệ thống đang idle.

    # ========================================================
    # LEADER ELECTION
    # ========================================================

    def _request_vote_from_peer(
        self,
        peer_id: str,
        peer_url: str,
        payload: dict
    ) -> tuple[str, dict | None, Exception | None]:
        """Gửi RequestVote tới một peer trong worker thread."""

        try:
            _, result = request_json(
                url=peer_url + "/raft/vote",
                method="POST",
                payload=payload,
                timeout=self.PEER_REQUEST_TIMEOUT_SECONDS
            )
            return peer_id, result, None
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError
        ) as error:
            return peer_id, None, error

    def begin_election(self, send_heartbeat: bool = True):
        with self.lock:
            self.role = "candidate"
            self.term += 1

            election_term = self.term

            self.voted_for = self.id
            self.leader_id = None

            self.last_heartbeat = time.monotonic()
            self.election_timeout = self._new_timeout()

            last_log_index = len(self.log)

            last_log_term = (
                self.log[-1].term
                if self.log
                else 0
            )

            self._persist()

            self.event(
                "ELECTION",
                (
                    f"Bắt đầu bầu Leader cho term "
                    f"{election_term}; tự bỏ phiếu cho {self.id}"
                )
            )

        # Nút ứng viên tự bỏ phiếu cho chính nó.
        votes = 1

        vote_payload = {
            "term": election_term,
            "candidate_id": self.id,
            "last_log_index": last_log_index,
            "last_log_term": last_log_term
        }

        if self.peers:
            with ThreadPoolExecutor(
                max_workers=len(self.peers),
                thread_name_prefix=f"vote-{self.id}"
            ) as executor:
                futures = [
                    executor.submit(
                        self._request_vote_from_peer,
                        peer_id,
                        peer_url,
                        vote_payload
                    )
                    for peer_id, peer_url in self.peers.items()
                ]

                for future in as_completed(futures):
                    peer_id, result, error = future.result()

                    if error is not None or result is None:
                        self.event(
                            "NODE_UNAVAILABLE",
                            (
                                f"Không liên lạc được {peer_id} "
                                "trong lúc bầu cử"
                            )
                        )
                        continue

                    response_term = int(result.get("term", 0))
                    if response_term > election_term:
                        self.become_follower(term=response_term)
                        return False

                    with self.lock:
                        still_candidate = (
                            self.role == "candidate"
                            and self.term == election_term
                        )

                    if not still_candidate:
                        return

                    if result.get("vote_granted"):
                        votes += 1
                        self.event(
                            "VOTE_RECEIVED",
                            f"Nhận phiếu từ {peer_id}"
                        )

        with self.lock:
            election_won = (
                self.role == "candidate"
                and self.term == election_term
                and votes >= self.majority
            )

            if election_won:
                self.role = "leader"
                self.leader_id = self.id
                self.voted_for = self.id
                self.peer_match_index = {
                    peer_id: 0
                    for peer_id in self.peers
                }

                self.event(
                    "LEADER",
                    (
                        f"Được bầu làm Leader term "
                        f"{election_term} với "
                        f"{votes}/{len(self.peers) + 1} phiếu"
                    )
                )

        if election_won and send_heartbeat:
            self.send_heartbeats()

        return election_won

    def _open_temporary_leader(self) -> bool:
        """Bầu một leader mới cho đúng một orchestration request."""

        with self.lock:
            # Một số embedders khôi phục/tiêm một leader đã được bầu sẵn.
            # Giữ quyền khởi tạo request đó nhưng vẫn mở term tạm thời mới;
            # election mạng đầy đủ chỉ cần thiết khi node đang idle.
            if self.role == "leader":
                self.term += 1
                self.voted_for = self.id
                self.leader_id = self.id
                self.last_heartbeat = time.monotonic()
                self.election_timeout = self._new_timeout()
                self._persist()
                return True

            self.role = "follower"
            self.leader_id = None

        return bool(self.begin_election(send_heartbeat=False))

    def _pause_after_orchestration(self):
        """Giải phóng leadership sau khi request thành công hoặc thất bại."""

        with self.lock:
            was_active = self.role in {"leader", "candidate"}
            self.role = "pause"
            self.leader_id = None
            self.last_heartbeat = time.monotonic()

            if was_active:
                self._persist()

                self.event(
                    "PAUSE",
                    f"Kết thúc orchestration tại {self.id}; tạm dừng Leader"
                )

    def become_follower(
        self,
        term: int,
        leader_id: str | None = None
    ):
        with self.lock:
            state_changed = (
                term != self.term
                or self.role != "follower"
                or self.leader_id != leader_id
            )

            if term > self.term:
                self.term = term
                self.voted_for = None

            self.role = "follower"
            self.leader_id = leader_id

            self.last_heartbeat = time.monotonic()
            self.election_timeout = self._new_timeout()

            if state_changed:
                self._persist()

                self.event(
                    "FOLLOWER",
                    (
                        f"Theo Leader "
                        f"{leader_id or 'chưa xác định'} "
                        f"ở term {term}"
                    )
                )

    # ========================================================
    # BỎ PHIẾU
    # ========================================================

    def vote(self, request: dict):
        with self.lock:
            requested_term = int(
                request["term"]
            )

            if requested_term < self.term:
                return {
                    "term": self.term,
                    "vote_granted": False
                }

            if requested_term > self.term:
                self.term = requested_term
                self.voted_for = None
                self.role = "follower"

            local_last_term = (
                self.log[-1].term
                if self.log
                else 0
            )

            local_last_index = len(self.log)

            candidate_log = (
                request.get("last_log_term", 0),
                request.get("last_log_index", 0)
            )

            local_log = (
                local_last_term,
                local_last_index
            )

            candidate_is_current = (
                candidate_log >= local_log
            )

            can_vote = self.voted_for in (
                None,
                request["candidate_id"]
            )

            vote_granted = (
                candidate_is_current
                and can_vote
            )

            if vote_granted:
                self.voted_for = request[
                    "candidate_id"
                ]

                self.last_heartbeat = (
                    time.monotonic()
                )

                self.election_timeout = (
                    self._new_timeout()
                )

            self._persist()

            decision = (
                "Chấp thuận"
                if vote_granted
                else "Từ chối"
            )

            self.event(
                "VOTE",
                (
                    f"{decision} bỏ phiếu cho "
                    f"{request['candidate_id']} "
                    f"ở term {requested_term}"
                )
            )

            return {
                "term": self.term,
                "vote_granted": vote_granted
            }

    # ========================================================
    # NHÂN BẢN DISTRIBUTED LOG
    # ========================================================

    @staticmethod
    def _same_entry(
        local_entry: LogEntry,
        incoming_entry: dict
    ) -> bool:
        """So sánh identity của log entry, bỏ qua committed flag."""

        return (
            incoming_entry.get("index") == local_entry.index
            and incoming_entry.get("term") == local_entry.term
            and incoming_entry.get("command") == local_entry.command
        )

    def append_entries(self, request: dict):
        """
        Nhận AppendEntries dạng incremental.

        Payload mới dùng prev_log_index/prev_log_term và chỉ chứa entry
        còn thiếu. Payload toàn bộ log của phiên bản cũ vẫn được hỗ trợ
        để đồng bộ dự phòng và giữ tương thích với dữ liệu đang chạy.
        """

        with self.lock:
            requested_term = int(request["term"])

            if requested_term < self.term:
                return {
                    "term": self.term,
                    "success": False,
                    "match_index": len(self.log)
                }

            self.become_follower(
                term=requested_term,
                leader_id=request.get("leader_id")
            )

            old_log_length = len(self.log)
            old_commit_index = self.commit_index
            old_services = {
                service: dict(nodes)
                for service, nodes in self.services.items()
            }

            incoming_data = request.get("entries", [])
            if not isinstance(incoming_data, list):
                return {
                    "term": self.term,
                    "success": False,
                    "match_index": len(self.log),
                    "error": "entries phải là một danh sách"
                }

            incremental = "prev_log_index" in request
            log_changed = False

            if incremental:
                prev_log_index = int(request.get("prev_log_index", 0))
                prev_log_term = int(request.get("prev_log_term", 0))

                if prev_log_index < 0 or prev_log_index > len(self.log):
                    return {
                        "term": self.term,
                        "success": False,
                        "match_index": len(self.log),
                        "error": "Follower đang thiếu log trước đó"
                    }

                if (
                    prev_log_index > 0
                    and self.log[prev_log_index - 1].term != prev_log_term
                ):
                    return {
                        "term": self.term,
                        "success": False,
                        "match_index": prev_log_index - 1,
                        "error": "prev_log_term không khớp"
                    }

                start_index = prev_log_index + 1
                for expected_index, item in enumerate(
                    incoming_data,
                    start=start_index
                ):
                    if (
                        not isinstance(item, dict)
                        or int(item.get("index", -1)) != expected_index
                    ):
                        return {
                            "term": self.term,
                            "success": False,
                            "match_index": prev_log_index,
                            "error": "Log index không liên tục"
                        }

                for offset, item in enumerate(incoming_data):
                    entry_index = start_index + offset

                    if entry_index <= len(self.log):
                        local_entry = self.log[entry_index - 1]
                        if self._same_entry(local_entry, item):
                            continue

                        if entry_index <= self.commit_index:
                            return {
                                "term": self.term,
                                "success": False,
                                "match_index": entry_index - 1,
                                "error": "Xung đột với log đã commit"
                            }

                        # Xóa suffix chưa commit bị xung đột.
                        del self.log[entry_index - 1:]
                        log_changed = True

                    # Thêm entry hiện tại và toàn bộ phần còn lại.
                    for remaining in incoming_data[offset:]:
                        entry_data = dict(remaining)
                        entry_data["committed"] = False
                        self.log.append(LogEntry(**entry_data))
                    if incoming_data[offset:]:
                        log_changed = True
                    break

                matched_index = prev_log_index + len(incoming_data)

            else:
                # Full-sync tương thích với payload cũ.
                for expected_index, item in enumerate(
                    incoming_data,
                    start=1
                ):
                    if (
                        not isinstance(item, dict)
                        or int(item.get("index", -1)) != expected_index
                    ):
                        return {
                            "term": self.term,
                            "success": False,
                            "match_index": len(self.log),
                            "error": "Log index không liên tục"
                        }

                if len(incoming_data) < self.commit_index:
                    return {
                        "term": self.term,
                        "success": False,
                        "match_index": len(self.log),
                        "error": "Không được ghi đè log đã commit"
                    }

                for index in range(self.commit_index):
                    if not self._same_entry(
                        self.log[index],
                        incoming_data[index]
                    ):
                        return {
                            "term": self.term,
                            "success": False,
                            "match_index": index,
                            "error": "Xung đột với log đã commit"
                        }

                current_identity = [
                    (entry.index, entry.term, entry.command)
                    for entry in self.log
                ]
                incoming_identity = [
                    (
                        int(item["index"]),
                        int(item["term"]),
                        item["command"]
                    )
                    for item in incoming_data
                ]

                if incoming_identity != current_identity:
                    self.log = []
                    for item in incoming_data:
                        entry_data = dict(item)
                        entry_data["committed"] = (
                            int(entry_data["index"]) <= self.commit_index
                        )
                        self.log.append(LogEntry(**entry_data))
                    log_changed = True

                matched_index = len(self.log)

            leader_commit = int(request.get("leader_commit", 0))
            new_commit_index = max(
                self.commit_index,
                min(leader_commit, len(self.log))
            )
            commit_changed = new_commit_index > self.commit_index

            if commit_changed:
                self.commit_index = new_commit_index
                self._apply_committed_entries()

            # _apply_committed_entries() chỉ đánh dấu và áp dụng phần mới
            # commit. Entry mới append đã được đặt committed=False, do đó
            # không cần quét lại toàn bộ log sau mỗi request.
            if log_changed or commit_changed:
                self._persist()

                if old_services != self.services:
                    self._request_reconcile()

            if len(self.log) > old_log_length:
                newest_entry = self.log[-1]
                self.event(
                    "REPLICATE",
                    (
                        f"Nhận log #{newest_entry.index}: "
                        f"{newest_entry.command.get('operation')} "
                        f"{newest_entry.command.get('service')}"
                    )
                )

            if self.commit_index > old_commit_index:
                self.event(
                    "APPLY",
                    (
                        f"Áp dụng log đã commit đến "
                        f"#{self.commit_index}; "
                        f"trạng thái dịch vụ đã đồng bộ"
                    )
                )

            return {
                "term": self.term,
                "success": True,
                "match_index": matched_index
            }
    # ========================================================
    # HEARTBEAT
    # ========================================================

    def _send_heartbeat_to_peer(
        self,
        peer_id: str,
        peer_url: str,
        payload: dict,
        leader_term: int
    ):
        """Gửi heartbeat tới một peer trong worker thread."""

        try:
            _, result = request_json(
                url=peer_url + "/raft/append",
                method="POST",
                payload=payload,
                timeout=self.PEER_REQUEST_TIMEOUT_SECONDS
            )

            response_term = int(result.get("term", 0))
            if response_term > leader_term:
                self.become_follower(term=response_term)
                return

            if result.get("success"):
                match_index = int(
                    result.get("match_index", 0)
                )
                with self.lock:
                    if (
                        self.role == "leader"
                        and self.term == leader_term
                    ):
                        self.peer_match_index[peer_id] = match_index
            else:
                self._sync_peer_full(peer_id, peer_url)

        except (
            OSError,
            urllib.error.URLError,
            TimeoutError
        ):
            return

    def send_heartbeats(self):
        # Không cho heartbeat định kỳ và heartbeat sau commit chồng nhau.
        if not self.heartbeat_lock.acquire(blocking=False):
            return

        try:
            self._send_heartbeats_parallel()
        finally:
            self.heartbeat_lock.release()

    def _send_heartbeats_parallel(self):
        with self.lock:
            if self.role != "leader":
                return

            leader_term = self.term
            last_log_index = len(self.log)
            last_log_term = (
                self.log[-1].term
                if self.log
                else 0
            )

            payload = {
                "term": leader_term,
                "leader_id": self.id,
                "prev_log_index": last_log_index,
                "prev_log_term": last_log_term,
                "entries": [],
                "leader_commit": self.commit_index
            }

        if not self.peers:
            return

        with ThreadPoolExecutor(
            max_workers=len(self.peers),
            thread_name_prefix=f"heartbeat-{self.id}"
        ) as executor:
            futures = [
                executor.submit(
                    self._send_heartbeat_to_peer,
                    peer_id,
                    peer_url,
                    payload,
                    leader_term
                )
                for peer_id, peer_url in self.peers.items()
            ]

            for future in as_completed(futures):
                future.result()

    def _sync_peer_full(
        self,
        peer_id: str,
        peer_url: str
    ) -> bool:
        """Đồng bộ toàn bộ log khi incremental AppendEntries thất bại."""

        with self.lock:
            if self.role != "leader":
                return False

            payload = {
                "term": self.term,
                "leader_id": self.id,
                "entries": [
                    asdict(entry)
                    for entry in self.log
                ],
                "leader_commit": self.commit_index
            }

        try:
            _, result = request_json(
                url=peer_url + "/raft/append",
                method="POST",
                payload=payload,
                timeout=0.65
            )

            if result.get("term", 0) > self.term:
                self.become_follower(term=int(result["term"]))
                return False

            if result.get("success"):
                with self.lock:
                    self.peer_match_index[peer_id] = int(
                        result.get("match_index", 0)
                    )
                return True

        except (
            OSError,
            urllib.error.URLError,
            TimeoutError
        ):
            pass

        return False

    def cluster_statuses(self) -> list[dict]:
        """
        Thu thập trạng thái tài nguyên của các node đang hoạt động.
        """

        statuses = [
            self.status()
        ]

        for peer_id, peer_url in self.peers.items():
            try:
                _, peer_status = request_json(
                    url=peer_url + "/status",
                    method="GET",
                    timeout=0.75
                )

                if isinstance(
                    peer_status,
                    dict
                ):
                    statuses.append(
                        peer_status
                    )

            except (
                OSError,
                urllib.error.URLError,
                TimeoutError
            ):
                # Node không phản hồi sẽ không được
                # đưa vào danh sách xếp hạng.
                continue

        return statuses


    def _choose_automatic_target(
        self,
        command: dict
    ) -> tuple[dict, list[dict]]:
        statuses = self.cluster_statuses()
        excluded_nodes: set[str] = set()

        operation = command["operation"]
        service = command["service"]

        if operation == "MIGRATE":
            source = command.get("source")

            if source:
                excluded_nodes.add(source)

        if operation == "REPLICATE":
            with self.lock:
                existing_nodes = set(
                    self.services.get(
                        service,
                        {}
                    )
                )

            reachable_nodes = {
                status["node_id"]
                for status in statuses
            }

            # Ưu tiên node chưa chạy service.
            available_new_nodes = (
                reachable_nodes
                - existing_nodes
            )

            if available_new_nodes:
                excluded_nodes.update(
                    existing_nodes
                )

        ranking = ResourceScheduler.rank(
            statuses,
            excluded_nodes=excluded_nodes
        )

        if not ranking:
            raise ValueError(
                "Không có Edge Node phù hợp"
            )

        return ranking[0], ranking

    # ========================================================
    # ĐIỀU PHỐI MICROSERVICE
    # ========================================================

    def orchestrate(self, command: dict):
        """
        Tuần tự hóa các proposal trên cùng một node.

        ThreadingHTTPServer có thể gọi orchestrate đồng thời. Nếu hai
        request cùng append log khi self.lock đang được nhả để gửi HTTP,
        index và commit_index có thể bị cập nhật sai thứ tự.
        """

        request_started = time.perf_counter()

        with self.orchestration_lock:
            lock_acquired = time.perf_counter()
            try:
                self._open_temporary_leader()
                status_code, result = self._orchestrate_serialized(command)
            finally:
                self._pause_after_orchestration()

        request_finished = time.perf_counter()
        gateway_metrics = {
            "queue_wait_ms": round(
                (lock_acquired - request_started) * 1000,
                3
            ),
            "total_ms": round(
                (request_finished - request_started) * 1000,
                3
            )
        }

        if isinstance(result, dict):
            result["gateway_metrics"] = gateway_metrics

        with self.lock:
            self._last_orchestration_metrics = {
                **gateway_metrics,
                "status_code": float(status_code)
            }

        return status_code, result

    def _orchestrate_serialized(
        self,
        command: dict
    ):
        phase_metrics: dict[str, float] = {
            "schedule_ms": 0.0,
            "proposal_persist_ms": 0.0,
            "replication_ms": 0.0,
            "commit_persist_ms": 0.0,
            "heartbeat_ms": 0.0
        }

        validation_error = (
            self._validate_command(command)
        )

        if validation_error:
            return 400, {
                "error": validation_error
            }

        # Chỉ đọc trạng thái trong lock.
        with self.lock:
            is_leader = (
                self.role == "leader"
            )

        # Không giữ lock khi gửi HTTP tới Leader.
        if not is_leader:
            return self._forward_to_leader(
                command
            )

        # Sao chép request để Leader có thể
        # thay target=AUTO thành node thực tế.
        command = dict(command)
        command["operation"] = str(
            command["operation"]
        ).strip().upper()
        command["service"] = str(
            command["service"]
        ).strip()
        command["target"] = str(
            command["target"]
        ).strip()
        command["replicas"] = int(
            command.get("replicas", 1)
        )

        if "source" in command:
            command["source"] = str(
                command["source"]
            ).strip()

        automatic_target = False
        schedule_decision = None

        requested_target = str(
            command.get(
                "target",
                ""
            )
        ).strip()

        if requested_target.upper() == "AUTO":
            automatic_target = True
            schedule_started = time.perf_counter()

            # REMOVE phải xác định chính xác
            # node cần gỡ service.
            if command["operation"] == "REMOVE":
                return 400, {
                    "error": (
                        "REMOVE phải chỉ định "
                        "target cụ thể"
                    )
                }

            try:
                (
                    schedule_decision,
                    _
                ) = self._choose_automatic_target(
                    command
                )

            except ValueError as error:
                return 503, {
                    "error": str(error)
                }

            # Thay AUTO bằng Edge Node được chọn.
            command["target"] = (
                schedule_decision["node_id"]
            )

            self.event(
                "SCHEDULE",
                (
                    f"Tự động chọn "
                    f"{command['target']} cho "
                    f"{command['operation']} "
                    f"{command['service']}; "
                    f"score="
                    f"{schedule_decision['score']}"
                )
            )

            phase_metrics["schedule_ms"] = round(
                (time.perf_counter() - schedule_started) * 1000,
                3
            )

        # Khi đã là Leader, tạo proposal trong lock.
        with self.lock:
            # Trạng thái có thể vừa thay đổi.
            if self.role != "leader":
                return 503, {
                    "error": (
                        "Leader vừa thay đổi, "
                        "vui lòng thử lại"
                    )
                }

            try:
                self.state_machine.validate(
                    command
                )
            except ValueError as error:
                return 400, {
                    "error": str(error)
                }

            self.event(
                "REQUEST",
                (
                    f"Leader tiếp nhận "
                    f"{command['operation']} "
                    f"{command['service']} "
                    f"-> {command['target']}"
                )
            )

            entry = LogEntry(
                index=len(self.log) + 1,
                term=self.term,
                command=command
            )

            self.log.append(entry)
            persist_started = time.perf_counter()
            self._persist()
            phase_metrics["proposal_persist_ms"] = round(
                (time.perf_counter() - persist_started) * 1000,
                3
            )

            self.event(
                "PROPOSE",
                (
                    f"Tạo đề xuất log #{entry.index} "
                    f"và gửi tới các Follower"
                )
            )

            prev_log_index = entry.index - 1
            prev_log_term = (
                self.log[prev_log_index - 1].term
                if prev_log_index > 0
                else 0
            )

            # Đường chạy bình thường chỉ gửi entry mới.
            payload = {
                "term": self.term,
                "leader_id": self.id,
                "prev_log_index": prev_log_index,
                "prev_log_term": prev_log_term,
                "entries": [asdict(entry)],
                "leader_commit": self.commit_index
            }

        # Gửi HTTP nhân bản khi không giữ self.lock.
        replication_started = time.perf_counter()
        acknowledgements = (
            self._replicate_proposal(
                entry=entry,
                payload=payload
            )
        )
        phase_metrics["replication_ms"] = round(
            (time.perf_counter() - replication_started) * 1000,
            3
        )
        phase_metrics["full_sync_fallbacks"] = float(
            self._last_replication_fallbacks
        )

        if acknowledgements < self.majority:
            # orchestration_lock bảo đảm entry này vẫn là proposal cuối.
            # Không giữ proposal đã bị từ chối trong log cục bộ, tránh
            # việc một commit về sau vô tình commit luôn entry cũ.
            with self.lock:
                if (
                    self.log
                    and self.log[-1].index == entry.index
                    and not self.log[-1].committed
                ):
                    self.log.pop()
                    self._persist()

            self.event(
                "REJECT",
                (
                    f"Log #{entry.index} không đủ đa số: "
                    f"{acknowledgements}/{self.majority}"
                )
            )

            # Thông báo lại log đã rollback cho các Follower còn sống.
            self.send_heartbeats()

            return 503, {
                "error": "Không đạt đa số",
                "acks": acknowledgements,
                "required": self.majority
            }

        with self.lock:
            # Kiểm tra lại trước khi commit.
            if self.role != "leader":
                return 503, {
                    "error": (
                        "Node không còn là Leader, "
                        "không thể commit"
                    )
                }

            self.commit_index = entry.index
            self._apply_committed_entries()
            persist_started = time.perf_counter()
            self._persist()
            phase_metrics["commit_persist_ms"] = round(
                (time.perf_counter() - persist_started) * 1000,
                3
            )

            self.event(
                "COMMIT",
                (
                    f"Commit log #{entry.index} với "
                    f"{acknowledgements}/"
                    f"{len(self.peers) + 1} nút; "
                    f"đã commit yêu cầu "
                    f"{command['operation']}"
                )
            )

        # Gửi commit_index mới cho các Follower trước.
        heartbeat_started = time.perf_counter()
        self.send_heartbeats()
        phase_metrics["heartbeat_ms"] = round(
            (time.perf_counter() - heartbeat_started) * 1000,
            3
        )

        # Sau đó yêu cầu luồng nền đồng bộ Docker
        # tại chính Leader nếu service thuộc node này.
        self._request_reconcile()

        return 201, {
            "status": "committed",
            "leader": self.id,
            "term": self.term,
            "log_index": entry.index,
            "acks": acknowledgements,
            "target": command["target"],
            "automatic_target": automatic_target,
            "schedule": schedule_decision,
            "leader_metrics": phase_metrics
        }
    
    def _validate_command(
        self,
        command: dict
    ) -> str | None:
        if not isinstance(command, dict):
            return "Nội dung yêu cầu phải là JSON object"

        required_fields = {
            "operation",
            "service",
            "target"
        }

        missing_fields = (
            required_fields
            - set(command)
        )

        if missing_fields:
            return (
                "Thiếu trường bắt buộc: "
                f"{sorted(missing_fields)}"
            )

        operation = command.get("operation")
        service = command.get("service")
        target = command.get("target")

        if not isinstance(operation, str):
            return "operation không hợp lệ"

        operation = operation.strip().upper()

        if operation not in self.VALID_OPERATIONS:
            return "Lệnh không hợp lệ"

        if not isinstance(service, str) or not service.strip():
            return "service không được để trống"

        if not isinstance(target, str) or not target.strip():
            return "target không được để trống"

        replicas_value = command.get("replicas", 1)

        if isinstance(replicas_value, bool):
            return "replicas phải là số nguyên dương"

        try:
            replicas = int(replicas_value)
        except (TypeError, ValueError):
            return "replicas phải là số nguyên dương"

        if replicas < 1:
            return "replicas phải lớn hơn hoặc bằng 1"

        if operation == "MIGRATE":
            source = command.get("source")

            if not isinstance(source, str) or not source.strip():
                return "MIGRATE cần trường source"

            if (
                target.strip().upper() != "AUTO"
                and source.strip() == target.strip()
            ):
                return (
                    "Node nguồn và node đích "
                    "phải khác nhau"
                )

        return None

    def _forward_to_leader(
        self,
        command: dict
    ):
        # Chỉ lấy thông tin Leader trong lock.
        with self.lock:
            leader_id = self.leader_id

            leader_url = self.peers.get(
                leader_id or ""
            )

        if not leader_url:
            return 503, {
                "error": (
                    "Chưa xác định Leader, "
                    "thử lại sau"
                )
            }

        self.event(
            "FORWARD",
            (
                f"Chuyển yêu cầu "
                f"{command['operation']} "
                f"{command['service']} "
                f"tới Leader {leader_id}"
            )
        )

        try:
            # Kết nối HTTP nằm hoàn toàn ngoài lock.
            return request_json(
                url=leader_url + "/orchestrate",
                method="POST",
                payload=command,
                timeout=5.0
            )

        except (
            OSError,
            urllib.error.URLError,
            TimeoutError
        ) as error:
            self.event(
                "FORWARD_FAILED",
                (
                    f"Không kết nối được "
                    f"Leader {leader_id}: {error}"
                )
            )

            return 503, {
                "error": (
                    f"Không kết nối được "
                    f"Leader {leader_id}"
                )
            }
        
    def _replicate_proposal(
        self,
        entry: LogEntry,
        payload: dict
    ) -> int:
        # Leader tự xác nhận log của mình.
        acknowledgements = 1
        fallback_count = 0

        def replicate_to_peer(
            peer_id: str,
            peer_url: str
        ) -> tuple[str, bool, bool, int]:
            try:
                _, result = request_json(
                    url=peer_url + "/raft/append",
                    method="POST",
                    payload=payload,
                    timeout=self.PEER_REQUEST_TIMEOUT_SECONDS
                )

                response_term = int(result.get("term", 0))
                if response_term > int(payload["term"]):
                    return peer_id, False, False, response_term

                used_fallback = False
                if not result.get("success"):
                    used_fallback = True
                    if self._sync_peer_full(peer_id, peer_url):
                        result = {
                            "success": True,
                            "match_index": entry.index,
                            "term": self.term
                        }

                success = bool(result.get("success"))
                if success:
                    with self.lock:
                        self.peer_match_index[peer_id] = int(
                            result.get("match_index", entry.index)
                        )

                return (
                    peer_id,
                    success,
                    used_fallback,
                    response_term
                )

            except (
                OSError,
                urllib.error.URLError,
                TimeoutError
            ):
                return peer_id, False, False, 0

        if self.peers:
            with ThreadPoolExecutor(
                max_workers=len(self.peers),
                thread_name_prefix=f"replicate-{self.id}"
            ) as executor:
                futures = [
                    executor.submit(
                        replicate_to_peer,
                        peer_id,
                        peer_url
                    )
                    for peer_id, peer_url in self.peers.items()
                ]

                for future in as_completed(futures):
                    (
                        peer_id,
                        success,
                        used_fallback,
                        response_term
                    ) = future.result()

                    if response_term > self.term:
                        self.become_follower(term=response_term)

                    if used_fallback:
                        fallback_count += 1

                    if success:
                        acknowledgements += 1
                        self.event(
                            "ACK",
                            (
                                f"Nhận chấp thuận từ {peer_id} "
                                f"cho log #{entry.index}"
                            )
                        )
                    else:
                        self.event(
                            "NODE_UNAVAILABLE",
                            (
                                "Không nhận được phản hồi hợp lệ "
                                f"từ {peer_id}"
                            )
                        )

        self._last_replication_fallbacks = fallback_count
        return acknowledgements

    # ========================================================
    # TRẠNG THÁI CHO GIAO DIỆN WEB
    # ========================================================

    def status(self):
        """
        Trả về trạng thái Raft và tài nguyên của Edge Node.
        """

        with self.lock:
            service_replicas = sum(
                int(
                    node_replicas.get(
                        self.id,
                        0
                    )
                )
                for node_replicas
                in self.services.values()
            )

            configured_nodes = len(self.peers) + 1

            node_status = {
                "node_id": self.id,
                "role": self.role,
                "term": self.term,
                "leader_id": self.leader_id,
                "commit_index": self.commit_index,
                "last_applied": self.last_applied,
                "log_length": len(self.log),

                # Tổng số thành viên trong cấu hình cluster.
                "configured_nodes": configured_nodes,

                # Số phiếu tối thiểu để bầu Leader và commit.
                "majority": self.majority,

                "service_replicas": (
                    service_replicas
                ),
                "replication": {
                    "peer_match_index": dict(
                        self.peer_match_index
                    ),
                    "last_full_sync_fallbacks": (
                        self._last_replication_fallbacks
                    )
                },
                "last_orchestration_metrics": dict(
                    self._last_orchestration_metrics
                )
            }

        # Không giữ self.lock khi đo CPU/RAM.
        node_status["resources"] = (
            ResourceMonitor.snapshot()
        )

        return node_status
