// LiveTaskMonitor.swift — live task progress in the one Jaeger menu bar item.
//
// Polls the Gateway's live task feed (GET /v1/live/tasks, built from the
// Gateway event stream: turn.start → tool.started / turn.progress →
// turn.finish / turn.failed). While anything runs:
//   • the status item shows a progress ring (StatusItemController.setLiveProgress)
//   • the menu lists running tasks with their current step (LiveTaskMenuSection)
//   • one native notification per task updates in place: the same identifier
//     ("jaeger-task-<request_id>") is re-added on each step so it replaces
//     itself; the final Done/Failed notification opens the conversation.
// Background turns (skill review, heartbeat) show in the menu only.
// Auth: the menubar caller token from ~/.jaeger/caller_tokens/menubar.token
// (0600, same user) so no Keychain prompt; the token is never logged.

import AppKit
import JaegerShellCore
import UserNotifications

struct LiveTask: Equatable {
    let requestId: String
    let sessionId: String
    let title: String
    let step: String
    let steps: Int
    let status: String
    let background: Bool
    let elapsed: Double
    let result: String

    init?(_ d: [String: Any]) {
        guard let rid = d["request_id"] as? String, !rid.isEmpty else { return nil }
        requestId = rid
        sessionId = d["session_id"] as? String ?? ""
        title = d["title"] as? String ?? "Jaeger task"
        step = d["step"] as? String ?? ""
        steps = d["steps"] as? Int ?? 0
        status = d["status"] as? String ?? "running"
        background = d["background"] as? Bool ?? false
        elapsed = d["elapsed_s"] as? Double ?? 0
        result = d["result"] as? String ?? ""
    }

    var elapsedText: String {
        let s = Int(elapsed)
        return s >= 60 ? "\(s / 60)m \(s % 60)s" : "\(s)s"
    }
}

final class LiveTaskMonitor {
    static let notifyAfter: Double = 8      // short chat replies never notify
    static let minUpdateGap: Double = 3     // in-place updates at most every 3s per task

    private weak var status: StatusItemController?
    private var timer: Timer?
    private(set) var running: [LiveTask] = []
    private(set) var recent: [LiveTask] = []
    private var lastSeq = -1
    private var notified: [String: (step: String, at: Date)] = [:]
    private var finishedNotified: Set<String> = []
    private var authorizationAsked = false
    private var loggedUnauthorized = false
    private var endpointUnsupported = false
    private var loggedUnsupported = false
    var onChange: (() -> Void)?

    init(status: StatusItemController) { self.status = status }

    func start() {
        schedule(1.5)
        poll()
    }

    private func schedule(_ interval: TimeInterval) {
        if let t = timer, abs(t.timeInterval - interval) < 0.01 { return }
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in self?.poll() }
    }

    static func token() -> String? {
        ShellEnvironment.callerToken()
    }

    private func poll() {
        guard !endpointUnsupported,
              let url = URL(string: ShellEnvironment.gateway().origin.string + "/v1/live/tasks") else { return }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 4)
        if let token = Self.token() {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        URLSession(configuration: .ephemeral).dataTask(with: req) { [weak self] data, response, _ in
            let statusCode = (response as? HTTPURLResponse)?.statusCode
            if let code = statusCode, LiveTasksResponsePolicy.shouldDisablePolling(statusCode: code) {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.endpointUnsupported = true
                    self.timer?.invalidate()
                    self.timer = nil
                    if !self.loggedUnsupported {
                        self.loggedUnsupported = true
                        shellLog("[shell][live-tasks] /v1/live/tasks not exposed by Gateway (HTTP \(code)); disabling live task polling")
                    }
                    self.apply(running: [], recent: [], seq: -2)
                }
                return
            }
            guard let data, statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                DispatchQueue.main.async { self?.apply(running: [], recent: [], seq: -2) }
                return
            }
            let run = (json["running"] as? [[String: Any]] ?? []).compactMap(LiveTask.init)
            let rec = (json["recent"] as? [[String: Any]] ?? []).compactMap(LiveTask.init)
            let seq = json["seq"] as? Int ?? 0
            DispatchQueue.main.async { self?.apply(running: run, recent: rec, seq: seq) }
        }.resume()
    }

    private func apply(running run: [LiveTask], recent rec: [LiveTask], seq: Int) {
        let changed = run != running || rec != recent
        running = run
        recent = rec
        let busy = !run.isEmpty
        status?.setLiveProgress(busy, foreground: run.contains { !$0.background }, count: run.count)
        if changed { onChange?() }
        if seq != lastSeq || busy { notify() }
        lastSeq = seq
    }

    // MARK: in-place notifications

    private func notify() {
        let now = Date()
        for task in running where !task.background && task.elapsed >= Self.notifyAfter {
            if let last = notified[task.requestId],
               last.step == task.step || now.timeIntervalSince(last.at) < Self.minUpdateGap { continue }
            notified[task.requestId] = (task.step, now)
            post(task, final: false)
        }
        for task in recent where notified[task.requestId] != nil && !finishedNotified.contains(task.requestId) {
            finishedNotified.insert(task.requestId)
            notified.removeValue(forKey: task.requestId)
            post(task, final: true)
        }
        if finishedNotified.count > 200 { finishedNotified.removeAll() }
    }

    private func post(_ task: LiveTask, final: Bool) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { [weak self] settings in
            guard let self else { return }
            if settings.authorizationStatus == .notDetermined && !self.authorizationAsked {
                self.authorizationAsked = true
                center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
                    shellLog("[shell][live-tasks] notification permission \(granted ? "granted" : "denied")")
                    if granted { self.deliver(task, final: final, center: center) }
                }
                return
            }
            guard [.authorized, .provisional].contains(settings.authorizationStatus) else {
                if !self.loggedUnauthorized {
                    self.loggedUnauthorized = true
                    shellLog("[shell][live-tasks] notifications not authorized (status \(settings.authorizationStatus.rawValue)); menu bar progress still shows")
                }
                return
            }
            self.deliver(task, final: final, center: center)
        }
    }

    private func deliver(_ task: LiveTask, final: Bool, center: UNUserNotificationCenter) {
        let content = UNMutableNotificationContent()
        if final {
            let failed = task.status == "failed"
            content.title = (failed ? "Failed: " : "Done: ") + task.title
            content.body = task.result.isEmpty ? (failed ? "Open Jaeger to see why." : "Click to see the result.") : task.result
            content.sound = .default
            content.interruptionLevel = .active
        } else {
            content.title = "Working: " + task.title
            content.body = "\(task.step) · step \(task.steps) · \(task.elapsedText)"
            content.interruptionLevel = .passive
        }
        content.threadIdentifier = "jaeger-live-tasks"
        let dest: NotificationDestination = NotificationDestination.validSession(task.sessionId)
            ? .conversation(task.sessionId) : .inbox
        content.userInfo = dest.payload
        let id = "jaeger-task-\(task.requestId)"
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil)) { error in
            shellLog("[shell][live-tasks] \(final ? "final" : "update") \(id) step=\(final ? task.status : task.step)\(error == nil ? "" : " error")")
        }
    }

    // MARK: menu section

    func menuItems(target: AnyObject, action: Selector) -> [NSMenuItem] {
        var items: [NSMenuItem] = []
        let header = NSMenuItem(title: running.isEmpty ? "Tasks: none running" : "Tasks running (\(running.count))",
                                action: nil, keyEquivalent: "")
        header.isEnabled = false
        items.append(header)
        for task in running {
            let item = NSMenuItem(title: "⟳ \(task.title) — \(task.step) (\(task.elapsedText))", action: action, keyEquivalent: "")
            item.target = target
            item.representedObject = task.sessionId
            item.toolTip = task.background ? "Background task" : "Step \(task.steps)"
            items.append(item)
        }
        for task in recent.prefix(3) {
            let mark = task.status == "failed" ? "✕" : "✓"
            let item = NSMenuItem(title: "\(mark) \(task.title) (\(task.elapsedText))", action: action, keyEquivalent: "")
            item.target = target
            item.representedObject = task.sessionId
            items.append(item)
        }
        return items
    }
}
