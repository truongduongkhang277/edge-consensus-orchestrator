DASHBOARD = r'''
<!doctype html>
<html lang="vi">
<head>
    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>Edge Consensus Orchestrator</title>

    <style>
        :root {
            color-scheme: dark;
            --background: #07111f;
            --panel: #10213a;
            --panel-secondary: #0c1a2e;
            --border: #294969;
            --text: #e8f0fd;
            --muted: #9db0c9;
            --blue: #48c7ff;
            --green: #50e3a4;
            --yellow: #ffc857;
            --red: #ff6b7a;
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            background: var(--background);
            color: var(--text);
            font: 15px system-ui, sans-serif;
        }

        main {
            max-width: 1380px;
            margin: auto;
            padding: 24px;
        }

        h1, h2, h3, p {
            margin-top: 0;
        }

        h1 {
            margin-bottom: 6px;
            color: var(--blue);
        }

        h2 {
            margin-bottom: 16px;
            font-size: 20px;
        }

        h3 {
            margin-bottom: 10px;
            font-size: 16px;
        }

        .muted {
            color: var(--muted);
        }

        .header-row,
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .summary {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin: 18px 0;
        }

        .summary-item {
            padding: 8px 12px;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--panel-secondary);
        }

        .summary-item.quorum-available {
            color: var(--green);
            border-color: var(--green);
        }

        .summary-item.quorum-lost {
            color: var(--red);
            border-color: var(--red);
        }

        .grid {
            display: grid;
            grid-template-columns:
                repeat(auto-fit, minmax(260px, 1fr));
            gap: 14px;
        }

        .two-columns {
            display: grid;
            grid-template-columns:
                minmax(0, 1.15fr)
                minmax(340px, 0.85fr);
            gap: 14px;
            margin-top: 14px;
        }

        .card {
            padding: 18px;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--panel);
        }

        .node-card {
            position: relative;
            overflow: hidden;
        }

        .node-card.leader {
            border-color: var(--green);
            box-shadow:
                0 0 0 1px rgba(80, 227, 164, 0.15);
        }

        .node-card.offline {
            border-color: var(--red);
            opacity: 0.75;
        }

        .role {
            display: inline-block;
            padding: 5px 9px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }

        .role.leader {
            color: #04150e;
            background: var(--green);
        }

        .role.follower {
            color: #06121d;
            background: var(--blue);
        }

        .role.offline {
            color: white;
            background: var(--red);
        }

        .node-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            margin-bottom: 15px;
        }

        .node-name {
            font-size: 18px;
            font-weight: 700;
        }

        .metrics {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 14px;
        }

        .metric {
            padding: 10px;
            border-radius: 10px;
            background: var(--panel-secondary);
        }

        .metric-label {
            color: var(--muted);
            font-size: 12px;
        }

        .metric-value {
            margin-top: 3px;
            font-size: 18px;
            font-weight: 700;
        }

        .progress {
            height: 6px;
            margin-top: 7px;
            overflow: hidden;
            border-radius: 999px;
            background: #21354e;
        }

        .progress > span {
            display: block;
            height: 100%;
            border-radius: inherit;
            background: var(--blue);
        }

        .progress.memory > span {
            background: var(--yellow);
        }

        .form-grid {
            display: grid;
            grid-template-columns:
                1fr 1.4fr 1.2fr 1.2fr 0.7fr;
            gap: 10px;
        }

        label {
            display: block;
            margin-bottom: 5px;
            color: var(--muted);
            font-size: 12px;
        }

        input,
        select,
        button {
            width: 100%;
            min-height: 42px;
            padding: 10px;
            border: 1px solid #426080;
            border-radius: 8px;
            background: #081629;
            color: white;
            font: inherit;
        }

        input:disabled,
        select:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        button {
            width: auto;
            padding: 10px 18px;
            border-color: #248bd9;
            background: #1478d4;
            font-weight: 650;
            cursor: pointer;
        }

        button:hover {
            background: #1b8ce9;
        }

        button:disabled {
            opacity: 0.6;
            cursor: wait;
        }

        .form-actions {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 12px;
            flex-wrap: wrap;
        }

        .operation-help {
            margin-top: 10px;
            color: var(--muted);
        }

        .decision {
            display: none;
            margin-top: 14px;
            padding: 14px;
            border: 1px solid var(--green);
            border-radius: 12px;
            background: rgba(80, 227, 164, 0.08);
        }

        .decision.visible {
            display: block;
        }

        .decision-grid {
            display: grid;
            grid-template-columns:
                repeat(auto-fit, minmax(140px, 1fr));
            gap: 8px;
            margin-top: 10px;
        }

        .decision-item {
            padding: 9px;
            border-radius: 8px;
            background: var(--panel-secondary);
        }

        .success {
            color: var(--green);
        }

        .error {
            color: var(--red);
        }

        pre {
            max-height: 280px;
            margin: 12px 0 0;
            padding: 12px;
            overflow: auto;
            border-radius: 10px;
            background: #071426;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .table-wrapper {
            overflow: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th,
        td {
            padding: 10px;
            border-bottom: 1px solid var(--border);
            text-align: left;
            white-space: nowrap;
        }

        th {
            color: var(--muted);
            font-size: 12px;
        }

        .event-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-height: 430px;
            overflow: auto;
        }

        .event {
            padding: 10px;
            border-left: 3px solid var(--blue);
            border-radius: 6px;
            background: var(--panel-secondary);
        }

        .event.SCHEDULE {
            border-left-color: var(--yellow);
        }

        .event.COMMIT {
            border-left-color: var(--green);
        }

        .event.REJECT,
        .event.NODE_UNAVAILABLE,
        .event.FORWARD_FAILED {
            border-left-color: var(--red);
        }

        .event-kind {
            color: var(--blue);
            font-size: 12px;
            font-weight: 700;
        }

        .event-time {
            float: right;
            color: var(--muted);
            font-size: 12px;
        }

        @media (max-width: 950px) {
            .two-columns {
                grid-template-columns: 1fr;
            }

            .form-grid {
                grid-template-columns: 1fr 1fr;
            }
        }

        @media (max-width: 600px) {
            main {
                padding: 14px;
            }

            .form-grid {
                grid-template-columns: 1fr;
            }

            .metrics {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>

<body>
<main>
    <div class="header-row">
        <div>
            <h1>Edge Consensus Orchestrator</h1>

            <p class="muted">
                Raft · Leader Election · Resource-aware Scheduling ·
                Distributed Log
            </p>
        </div>

        <div class="muted" id="last-updated">
            Đang kết nối...
        </div>
    </div>

    <div class="summary">
        <div class="summary-item">
            Configured:
            <strong id="configured-count">-</strong>
        </div>

        <div class="summary-item">
            Majority:
            <strong id="majority-count">-</strong>
        </div>

        <div class="summary-item" id="quorum-box">
            Quorum:
            <strong id="quorum-status">-</strong>
        </div>

        <div class="summary-item">
            Leader:
            <strong id="leader-name">-</strong>
        </div>

        <div class="summary-item">
            Term:
            <strong id="current-term">-</strong>
        </div>

        <div class="summary-item">
            Commit:
            <strong id="current-commit">-</strong>
        </div>
    </div>

    <div id="nodes" class="grid"></div>

    <section class="card" style="margin-top:14px">
        <h2>Gửi lệnh điều phối Microservice</h2>

        <div class="form-grid">
            <div>
                <label for="op">Thao tác</label>

                <select id="op">
                    <option value="DEPLOY">DEPLOY</option>
                    <option value="REPLICATE">REPLICATE</option>
                    <option value="MIGRATE">MIGRATE</option>
                    <option value="REMOVE">REMOVE</option>
                </select>
            </div>

            <div>
                <label for="service">Microservice</label>

                <input
                    id="service"
                    value="patient-api"
                    placeholder="Ví dụ: patient-api"
                >
            </div>

            <div>
                <label for="source">Node nguồn</label>

                <select id="source">
                    <option value="">Không sử dụng</option>
                    <option value="edge-1">edge-1</option>
                    <option value="edge-2">edge-2</option>
                    <option value="edge-3">edge-3</option>
                </select>
            </div>

            <div>
                <label for="target">Node đích</label>

                <select id="target">
                    <option value="AUTO">
                        AUTO – Scheduler
                    </option>

                    <option value="edge-1">edge-1</option>
                    <option value="edge-2">edge-2</option>
                    <option value="edge-3">edge-3</option>
                </select>
            </div>

            <div>
                <label for="replicas">Số replica</label>

                <input
                    id="replicas"
                    value="1"
                    type="number"
                    min="1"
                >
            </div>
        </div>

        <div class="operation-help" id="operation-help"></div>

        <div class="form-actions">
            <button id="send-button">
                Commit qua Consensus
            </button>

            <span id="request-status" class="muted"></span>
        </div>

        <div id="decision" class="decision"></div>

        <details style="margin-top:14px">
            <summary>Phản hồi JSON</summary>
            <pre id="result">Chưa gửi lệnh.</pre>
        </details>
    </section>

    <div class="two-columns">
        <section class="card">
            <div class="section-header">
                <h2>Trạng thái Microservices</h2>
                <span class="muted">Distributed state</span>
            </div>

            <div
                id="services"
                class="table-wrapper"
            ></div>
        </section>

        <section class="card">
            <div class="section-header">
                <h2>Sự kiện Consensus</h2>
                <span class="muted">Theo Leader hiện tại</span>
            </div>

            <div id="events" class="event-list"></div>
        </section>
    </div>

    <section class="card" style="margin-top:14px">
        <div class="section-header">
            <h2>Distributed Log</h2>
            <span class="muted">Các lệnh đã nhân bản</span>
        </div>

        <div id="log-table" class="table-wrapper"></div>
    </section>
</main>

<script>
    const ports = Array.from(
        { length: 12 },
        (_, index) => 8001 + index
    );

    const elements = {
        nodes: document.getElementById("nodes"),
        onlineCount: document.getElementById("online-count"),
        configuredCount: document.getElementById(
            "configured-count"
        ),
        majorityCount: document.getElementById(
            "majority-count"
        ),
        quorumBox: document.getElementById(
            "quorum-box"
        ),
        quorumStatus: document.getElementById(
            "quorum-status"
        ),
        leaderName: document.getElementById("leader-name"),
        currentTerm: document.getElementById("current-term"),
        currentCommit: document.getElementById("current-commit"),
        lastUpdated: document.getElementById("last-updated"),
        operation: document.getElementById("op"),
        service: document.getElementById("service"),
        source: document.getElementById("source"),
        target: document.getElementById("target"),
        replicas: document.getElementById("replicas"),
        sendButton: document.getElementById("send-button"),
        requestStatus: document.getElementById("request-status"),
        operationHelp: document.getElementById("operation-help"),
        decision: document.getElementById("decision"),
        result: document.getElementById("result"),
        services: document.getElementById("services"),
        events: document.getElementById("events"),
        logTable: document.getElementById("log-table")
    };

    let leaderPort = null;
    let refreshing = false;

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function numberValue(value, fallback = 0) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function clamp(value) {
        return Math.max(0, Math.min(100, value));
    }

    function currentScore(status) {
        const resources = status.resources || {};
        const cpu = numberValue(resources.cpu_percent);
        const memory = numberValue(resources.memory_percent);
        const replicas = numberValue(status.service_replicas);
        const replicaLoad = clamp(replicas * 25);

        return (
            0.5 * cpu
            + 0.3 * memory
            + 0.2 * replicaLoad
        ).toFixed(2);
    }

    async function getJson(url) {
        const response = await fetch(
            url,
            {
                cache: "no-store"
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        return response.json();
    }

    function renderNodes(nodeResults) {
        const cards = nodeResults.map(item => {
            if (!item.online) {
                return `
                    <div class="card node-card offline">
                        <div class="node-title">
                            <span class="node-name">
                                port ${item.port}
                            </span>

                            <span class="role offline">
                                OFFLINE
                            </span>
                        </div>

                        <div class="muted">
                            Không kết nối được Edge Node
                        </div>
                    </div>
                `;
            }

            const status = item.status;
            const resources = status.resources || {};

            const cpu = numberValue(
                resources.cpu_percent
            );

            const memory = numberValue(
                resources.memory_percent
            );

            const role = String(
                status.role || "follower"
            ).toLowerCase();

            return `
                <div class="card node-card ${role}">
                    <div class="node-title">
                        <span class="node-name">
                            ${escapeHtml(status.node_id)}
                        </span>

                        <span class="role ${role}">
                            ${escapeHtml(role.toUpperCase())}
                        </span>
                    </div>

                    <div class="muted">
                        Term ${escapeHtml(status.term)}
                        · Commit ${escapeHtml(status.commit_index)}
                        · Leader ${escapeHtml(status.leader_id || "-")}
                    </div>

                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">
                                CPU
                            </div>

                            <div class="metric-value">
                                ${cpu.toFixed(1)}%
                            </div>

                            <div class="progress">
                                <span style="width:${clamp(cpu)}%"></span>
                            </div>
                        </div>

                        <div class="metric">
                            <div class="metric-label">
                                RAM
                            </div>

                            <div class="metric-value">
                                ${memory.toFixed(1)}%
                            </div>

                            <div class="progress memory">
                                <span style="width:${clamp(memory)}%"></span>
                            </div>
                        </div>

                        <div class="metric">
                            <div class="metric-label">
                                Service replicas
                            </div>

                            <div class="metric-value">
                                ${escapeHtml(status.service_replicas)}
                            </div>
                        </div>

                        <div class="metric">
                            <div class="metric-label">
                                Score hiện tại
                            </div>

                            <div class="metric-value">
                                ${currentScore(status)}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        elements.nodes.innerHTML = cards.join("");
    }

    function renderServices(services) {
        const rows = [];

        for (
            const [serviceName, placements]
            of Object.entries(services || {})
        ) {
            for (
                const [nodeId, replicaCount]
                of Object.entries(placements || {})
            ) {
                rows.push(`
                    <tr>
                        <td>${escapeHtml(serviceName)}</td>
                        <td>${escapeHtml(nodeId)}</td>
                        <td>${escapeHtml(replicaCount)}</td>
                    </tr>
                `);
            }
        }

        if (!rows.length) {
            elements.services.innerHTML = `
                <p class="muted">
                    Chưa có microservice được triển khai.
                </p>
            `;
            return;
        }

        elements.services.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Microservice</th>
                        <th>Edge Node</th>
                        <th>Replica</th>
                    </tr>
                </thead>

                <tbody>
                    ${rows.join("")}
                </tbody>
            </table>
        `;
    }

    function renderLog(entries) {
        if (!Array.isArray(entries) || !entries.length) {
            elements.logTable.innerHTML = `
                <p class="muted">
                    Distributed log đang trống.
                </p>
            `;
            return;
        }

        const sortedEntries = [...entries]
            .sort(
                (left, right) =>
                    numberValue(right.index)
                    - numberValue(left.index)
            )
            .slice(0, 15);

        const rows = sortedEntries.map(entry => {
            const command = entry.command || {};

            return `
                <tr>
                    <td>${escapeHtml(entry.index)}</td>
                    <td>${escapeHtml(entry.term)}</td>
                    <td>${escapeHtml(command.operation)}</td>
                    <td>${escapeHtml(command.service)}</td>
                    <td>${escapeHtml(command.source || "-")}</td>
                    <td>${escapeHtml(command.target || "-")}</td>
                    <td>${escapeHtml(command.replicas ?? "-")}</td>
                    <td class="${entry.committed ? "success" : "error"}">
                        ${entry.committed ? "COMMITTED" : "PENDING"}
                    </td>
                </tr>
            `;
        });

        elements.logTable.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Index</th>
                        <th>Term</th>
                        <th>Operation</th>
                        <th>Service</th>
                        <th>Source</th>
                        <th>Target</th>
                        <th>Replica</th>
                        <th>Trạng thái</th>
                    </tr>
                </thead>

                <tbody>
                    ${rows.join("")}
                </tbody>
            </table>
        `;
    }

    function renderEvents(events) {
        if (!Array.isArray(events) || !events.length) {
            elements.events.innerHTML = `
                <p class="muted">
                    Chưa có sự kiện.
                </p>
            `;
            return;
        }

        const sortedEvents = [...events]
            .sort(
                (left, right) =>
                    numberValue(right.timestamp)
                    - numberValue(left.timestamp)
            )
            .slice(0, 15);

        elements.events.innerHTML = sortedEvents
            .map(event => `
                <div class="event ${escapeHtml(event.kind)}">
                    <span class="event-kind">
                        ${escapeHtml(event.kind)}
                    </span>

                    <span class="event-time">
                        ${escapeHtml(event.time)}
                    </span>

                    <div style="margin-top:5px">
                        ${escapeHtml(event.message)}
                    </div>
                </div>
            `)
            .join("");
    }

    function renderDecision(data, httpStatus) {
        elements.result.textContent = JSON.stringify(
            data,
            null,
            2
        );

        if (!data || data.status !== "committed") {
            elements.decision.className = "decision visible";

            elements.decision.innerHTML = `
                <h3 class="error">
                    Không thể commit yêu cầu
                </h3>

                <div>
                    HTTP ${escapeHtml(httpStatus)}:
                    ${escapeHtml(data?.error || "Lỗi không xác định")}
                </div>
            `;

            return;
        }

        const schedule = data.schedule;

        if (
            data.automatic_target
            && schedule
        ) {
            elements.decision.className = "decision visible";

            elements.decision.innerHTML = `
                <h3 class="success">
                    Scheduler đã tự động chọn
                    ${escapeHtml(data.target)}
                </h3>

                <div class="muted">
                    Score được ghi nhận trước khi triển khai replica.
                </div>

                <div class="decision-grid">
                    <div class="decision-item">
                        <div class="metric-label">Score</div>
                        <strong>${escapeHtml(schedule.score)}</strong>
                    </div>

                    <div class="decision-item">
                        <div class="metric-label">CPU</div>
                        <strong>
                            ${escapeHtml(schedule.cpu_percent)}%
                        </strong>
                    </div>

                    <div class="decision-item">
                        <div class="metric-label">RAM</div>
                        <strong>
                            ${escapeHtml(schedule.memory_percent)}%
                        </strong>
                    </div>

                    <div class="decision-item">
                        <div class="metric-label">
                            Replica trước triển khai
                        </div>

                        <strong>
                            ${escapeHtml(schedule.service_replicas)}
                        </strong>
                    </div>

                    <div class="decision-item">
                        <div class="metric-label">
                            Consensus ACK
                        </div>

                        <strong>
                            ${escapeHtml(data.acks)}/3
                        </strong>
                    </div>
                </div>
            `;

            return;
        }

        elements.decision.className = "decision visible";

        elements.decision.innerHTML = `
            <h3 class="success">
                Đã commit tại ${escapeHtml(data.target)}
            </h3>

            <div>
                Log #${escapeHtml(data.log_index)}
                · Term ${escapeHtml(data.term)}
                · ACK ${escapeHtml(data.acks)}/3
            </div>
        `;
    }

    function updateForm() {
        const operation = elements.operation.value;
        const autoOption = elements.target.querySelector(
            'option[value="AUTO"]'
        );

        const isMigrate = operation === "MIGRATE";
        const isRemove = operation === "REMOVE";

        elements.source.disabled = !isMigrate;
        elements.replicas.disabled = isRemove;
        autoOption.disabled = isRemove;

        if (!isMigrate) {
            elements.source.value = "";
        }

        if (
            isRemove
            && elements.target.value === "AUTO"
        ) {
            elements.target.value = "edge-1";
        }

        const help = {
            DEPLOY:
                "Khởi tạo microservice trên node đích. "
                + "AUTO chọn node có tải phù hợp nhất.",

            REPLICATE:
                "Tạo thêm replica. AUTO ưu tiên node "
                + "chưa chạy microservice.",

            MIGRATE:
                "Di chuyển microservice từ node nguồn "
                + "sang node đích. Target có thể là AUTO.",

            REMOVE:
                "Gỡ microservice khỏi một node cụ thể; "
                + "không hỗ trợ Target AUTO."
        };

        elements.operationHelp.textContent = (
            help[operation]
        );
    }

    async function refresh() {
        if (refreshing) {
            return;
        }

        refreshing = true;

        try {
            const nodeResults = await Promise.all(
                ports.map(async port => {
                    try {
                        const status = await getJson(
                            `http://localhost:${port}/status`
                        );

                        return {
                            port,
                            online: true,
                            status
                        };

                    } catch (error) {
                        return {
                            port,
                            online: false,
                            error
                        };
                    }
                })
            );

            renderNodes(nodeResults);

            const leader = onlineNodes.find(
                item => item.status.role === "leader"
            );

            leaderPort = leader?.port || null;

            /*
            * Lấy cấu hình cluster từ Leader hoặc một node online.
            * Nếu backend cũ chưa có configured_nodes thì dùng ports.length.
            */
            const referenceStatus = (
                leader?.status
                || onlineNodes[0]?.status
                || {}
            );

            const configuredNodes = Number(
                referenceStatus.configured_nodes
                ?? ports.length
            );

            const majority = Number(
                referenceStatus.majority
                ?? Math.floor(configuredNodes / 2) + 1
            );

            const quorumAvailable = (
                onlineNodes.length >= majority
            );

            elements.onlineCount.textContent = (
                `${onlineNodes.length}/${configuredNodes}`
            );

            elements.configuredCount.textContent = (
                configuredNodes
            );

            elements.majorityCount.textContent = (
                majority
            );

            elements.quorumStatus.textContent = (
                quorumAvailable
                    ? "AVAILABLE"
                    : "LOST"
            );

            elements.quorumBox.classList.toggle(
                "quorum-available",
                quorumAvailable
            );

            elements.quorumBox.classList.toggle(
                "quorum-lost",
                !quorumAvailable
            );

            elements.leaderName.textContent = (
                leader?.status.node_id || "-"
            );

            elements.currentTerm.textContent = (
                leader?.status.term
                ?? onlineNodes[0]?.status.term
                ?? "-"
            );

            elements.currentCommit.textContent = (
                leader?.status.commit_index
                ?? onlineNodes[0]?.status.commit_index
                ?? "-"
            );

            elements.lastUpdated.textContent = (
                "Cập nhật "
                + new Date().toLocaleTimeString("vi-VN")
            );

            const dataPort = (
                leaderPort
                || onlineNodes[0]?.port
            );

            if (!dataPort) {
                renderServices({});
                renderLog([]);
                renderEvents([]);
                return;
            }

            const baseUrl = (
                `http://localhost:${dataPort}`
            );

            const [
                servicesResult,
                logResult,
                eventsResult
            ] = await Promise.allSettled([
                getJson(baseUrl + "/services"),
                getJson(baseUrl + "/log"),
                getJson(baseUrl + "/events")
            ]);

            renderServices(
                servicesResult.status === "fulfilled"
                    ? servicesResult.value
                    : {}
            );

            renderLog(
                logResult.status === "fulfilled"
                    ? logResult.value
                    : []
            );

            renderEvents(
                eventsResult.status === "fulfilled"
                    ? eventsResult.value
                    : []
            );

        } finally {
            refreshing = false;
        }
    }

    async function sendCommand() {
        const operation = elements.operation.value;
        const service = elements.service.value.trim();
        const source = elements.source.value;
        const target = elements.target.value;

        const replicas = Math.max(
            1,
            parseInt(
                elements.replicas.value,
                10
            ) || 1
        );

        if (!service) {
            elements.requestStatus.className = "error";
            elements.requestStatus.textContent = (
                "Vui lòng nhập tên microservice."
            );
            return;
        }

        if (
            operation === "MIGRATE"
            && !source
        ) {
            elements.requestStatus.className = "error";
            elements.requestStatus.textContent = (
                "MIGRATE cần chọn node nguồn."
            );
            return;
        }

        if (
            operation === "MIGRATE"
            && target !== "AUTO"
            && source === target
        ) {
            elements.requestStatus.className = "error";
            elements.requestStatus.textContent = (
                "Node nguồn và node đích phải khác nhau."
            );
            return;
        }

        const body = {
            operation,
            service,
            target,
            replicas
        };

        if (source) {
            body.source = source;
        }

        elements.sendButton.disabled = true;
        elements.requestStatus.className = "muted";
        elements.requestStatus.textContent = (
            "Đang gửi yêu cầu tới cụm..."
        );

        try {
            const response = await fetch(
                "/orchestrate",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(body)
                }
            );

            const data = await response.json();

            renderDecision(
                data,
                response.status
            );

            elements.requestStatus.className = (
                response.ok
                    ? "success"
                    : "error"
            );

            elements.requestStatus.textContent = (
                response.ok
                    ? "Đã đạt đồng thuận và commit."
                    : "Yêu cầu không được commit."
            );

            await refresh();

        } catch (error) {
            elements.requestStatus.className = "error";
            elements.requestStatus.textContent = (
                "Không kết nối được Edge Node."
            );

            elements.result.textContent = String(error);

        } finally {
            elements.sendButton.disabled = false;
        }
    }

    elements.operation.addEventListener(
        "change",
        updateForm
    );

    elements.sendButton.addEventListener(
        "click",
        sendCommand
    );

    updateForm();
    refresh();

    setInterval(
        refresh,
        1500
    );
</script>
</body>
</html>
'''