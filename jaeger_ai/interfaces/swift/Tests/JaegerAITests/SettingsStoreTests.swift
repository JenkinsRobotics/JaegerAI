//
//  SettingsStoreTests.swift
//
//  Pins the native settings contract against a scripted bridge that behaves
//  like ``interfaces/bridge.py`` + ``core/settings/catalog.py``: the catalog
//  masks secrets behind ``configured``, ``settings_set`` echoes the RAW stored
//  value (a list for json, "" for secrets), and a reply can fail after the
//  write already landed (the unserializable-Path case).
//

import Combine
import XCTest
@testable import JaegerAI

@MainActor
final class SettingsStoreTests: XCTestCase {

    // MARK: - load

    func testLoadFailureIsReportedWithActionableMessageAndRetryRecovers() async {
        let (store, backend) = makeStore()
        backend.queryError = "not connected"

        await store.loadSettingsCatalog()

        XCTAssertTrue(store.settingsGroups.isEmpty)
        guard case .failed(let message) = store.settingsLoad else {
            return XCTFail("load failure was silent: \(store.settingsLoad)")
        }
        XCTAssertTrue(message.contains("isn't connected"), message)
        XCTAssertTrue(message.contains("Retry"), message)

        backend.queryError = nil
        await store.loadSettingsCatalog(force: true)   // what Retry calls

        XCTAssertEqual(store.settingsLoad, .loaded)
        XCTAssertEqual(current(store, "model.ctx"), .int(2048))
    }

    func testUndecodableCatalogIsReportedNotSwallowed() async {
        let (store, backend) = makeStore()
        backend.catalogOverride = Data(#"{"model": [{"path": "model.ctx"}]}"#.utf8)

        await store.loadSettingsCatalog()

        guard case .failed(let message) = store.settingsLoad else {
            return XCTFail("decode failure was silent")
        }
        XCTAssertTrue(message.contains("different versions"), message)
        XCTAssertTrue(message.contains("missing"), message)
    }

    func testFailedRefreshKeepsLastValuesAndSaysSo() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        backend.queryError = "bridge timed out"

        await store.loadSettingsCatalog(force: true)

        XCTAssertEqual(current(store, "model.ctx"), .int(2048))
        guard case .failed(let message) = store.settingsLoad else {
            return XCTFail("refresh failure was silent")
        }
        XCTAssertTrue(message.contains("didn't answer in time"), message)
    }

    func testLoadFailureMessages() {
        XCTAssertTrue(SettingsStore.loadFailureMessage("bridge not running")
            .contains("isn't connected"))
        XCTAssertTrue(SettingsStore.loadFailureMessage(nil)
            .contains("unknown bridge error"))
        XCTAssertEqual(SettingsStore.loadFailureMessage("1 validation error for Config"),
                       "Couldn't load settings: 1 validation error for Config")
    }

    // MARK: - save shows what the backend stored

    func testSaveShowsBackendNormalizedValueNotSubmittedValue() async {
        let (store, _) = makeStore()
        await store.loadSettingsCatalog()

        let ok = await store.setSetting("persona.greeting", .string("  hello  "))

        XCTAssertTrue(ok)
        XCTAssertEqual(current(store, "persona.greeting"), .string("hello"))
        XCTAssertEqual(store.settingSaves["persona.greeting"], .saved(restartRequired: false))
    }

    func testSaveFallsBackToEchoedValueWhenReadBackFails() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        backend.failGroupQueries = true

        await store.setSetting("model.ctx", .string("4096"))

        XCTAssertEqual(current(store, "model.ctx"), .int(4096))
        XCTAssertEqual(store.settingSaves["model.ctx"], .saved(restartRequired: true))
    }

    func testJSONSaveWithoutReadBackIsUnconfirmedNotGuessed() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        let before = current(store, "model.extra_gguf_dirs")
        backend.failGroupQueries = true

        let ok = await store.setSetting("model.extra_gguf_dirs", .string(#"["/models"]"#))

        XCTAssertTrue(ok)
        // The echo is a raw list, not the catalog's display string: keep the
        // old value and say the save is unconfirmed rather than show a blank.
        XCTAssertEqual(current(store, "model.extra_gguf_dirs"), before)
        XCTAssertEqual(store.settingSaves["model.extra_gguf_dirs"],
                       .savedUnconfirmed(restartRequired: true))
    }

    func testRejectedSaveKeepsStoredValueAndReportsError() async {
        let (store, _) = makeStore()
        await store.loadSettingsCatalog()

        let ok = await store.setSetting("model.ctx", .int(7))

        XCTAssertFalse(ok)
        XCTAssertEqual(current(store, "model.ctx"), .int(2048))
        guard case .failed(let message)? = store.settingSaves["model.ctx"] else {
            return XCTFail("rejection not reported")
        }
        XCTAssertTrue(message.contains("greater than or equal to 512"), message)
        XCTAssertFalse(store.settingsRestartNeeded)
    }

    func testErrorReplyAfterLandedWriteShowsWhatWasStored() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        backend.replyErrorAfterWrite = "Object of type PosixPath is not JSON serializable"

        let ok = await store.setSetting("model.ctx", .int(4096))

        XCTAssertFalse(ok)
        XCTAssertEqual(current(store, "model.ctx"), .int(4096))
        guard case .failed(let message)? = store.settingSaves["model.ctx"] else {
            return XCTFail("error reply not reported")
        }
        XCTAssertTrue(message.contains("changed anyway"), message)
    }

    // MARK: - secrets

    func testSecretShowsConfiguredStatusWithoutHoldingTheSecret() async throws {
        let (store, _) = makeStore()
        await store.loadSettingsCatalog()
        XCTAssertEqual(setting(store, "webhooks.secret")?.configured, false)

        let ok = await store.setSetting("webhooks.secret", .string("sk-private-value"))

        XCTAssertTrue(ok)
        let secret = try XCTUnwrap(setting(store, "webhooks.secret"))
        XCTAssertEqual(secret.configured, true)
        XCTAssertEqual(secret.current, .string(""))
        let held = try JSONEncoder().encode(store.settingsGroups.flatMap(\.settings))
        XCTAssertFalse(String(decoding: held, as: UTF8.self).contains("sk-private-value"))
    }

    // MARK: - saved versus applied

    func testSavedStateCarriesRestartRequirementAndNeverClaimsApplied() async {
        let (store, _) = makeStore()
        await store.loadSettingsCatalog()

        await store.setSetting("display.show_latency", .bool(true))
        XCTAssertEqual(store.settingSaves["display.show_latency"], .saved(restartRequired: false))
        XCTAssertFalse(store.settingsRestartNeeded)

        await store.setSetting("model.ctx", .int(4096))
        XCTAssertEqual(store.settingSaves["model.ctx"], .saved(restartRequired: true))
        XCTAssertTrue(store.settingsRestartNeeded)
    }

    // MARK: - rapid edits

    func testRapidEditsNewestValueWinsAndQueuedEditsCoalesce() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        let seen = record(store, "model.ctx")
        let reached = Gate(), release = Gate()
        backend.beforeSet = { _ in
            if backend.sets.count == 1 { reached.open(); await release.wait() }
        }

        let first = Task { await store.setSetting("model.ctx", .int(4096)) }
        await reached.wait()
        let second = Task { await store.setSetting("model.ctx", .int(8192)) }
        let third = Task { await store.setSetting("model.ctx", .int(16384)) }
        await settle()
        release.open()
        let results = (await first.value, await second.value, await third.value)

        XCTAssertEqual(results.0, true)    // its write succeeded, but lost the row
        XCTAssertEqual(results.1, false)   // superseded before it was sent
        XCTAssertEqual(results.2, true)
        XCTAssertEqual(backend.sets.map(\.value), [.int(4096), .int(16384)])
        XCTAssertEqual(current(store, "model.ctx"), .int(16384))
        XCTAssertEqual(store.settingSaves["model.ctx"], .saved(restartRequired: true))
        XCTAssertFalse(seen.values.contains(.int(4096)),
                       "an older response was published over a newer edit: \(seen.values)")
        // What the row shows must be what's on disk: writes land in edit order.
        await store.loadSettingsCatalog(force: true)
        XCTAssertEqual(current(store, "model.ctx"), .int(16384))
    }

    func testOlderReadBackCannotOverwriteNewerEdit() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        let seen = record(store, "display.show_latency")
        let reached = Gate(), release = Gate()
        backend.afterSnapshot = { group in
            if group != nil, backend.sets.count == 1 { reached.open(); await release.wait() }
        }

        let first = Task { await store.setSetting("display.show_latency", .bool(true)) }
        await reached.wait()   // first write landed; its read-back (true) is in flight
        let second = Task { await store.setSetting("display.show_latency", .bool(false)) }
        await settle()
        release.open()
        _ = await first.value
        _ = await second.value

        XCTAssertEqual(current(store, "display.show_latency"), .bool(false))
        XCTAssertFalse(seen.values.contains(.bool(true)),
                       "stale read-back flashed over the newer edit: \(seen.values)")
    }

    func testCatalogLoadStartedBeforeSaveCannotRevertIt() async {
        let (store, backend) = makeStore()
        await store.loadSettingsCatalog()
        let reached = Gate(), release = Gate()
        backend.afterSnapshot = { group in
            if group == nil { reached.open(); await release.wait() }
        }

        let load = Task { await store.loadSettingsCatalog(force: true) }
        await reached.wait()   // the load has read the file (ctx = 2048)
        backend.afterSnapshot = nil
        await store.setSetting("model.ctx", .int(4096))
        release.open()
        await load.value

        XCTAssertEqual(store.settingsLoad, .loaded)
        XCTAssertEqual(current(store, "model.ctx"), .int(4096))

        // A load that starts after the save sees the file, including edits
        // made elsewhere (CLI, another client).
        backend.setStored("model.ctx", 32768)
        await store.loadSettingsCatalog(force: true)
        XCTAssertEqual(current(store, "model.ctx"), .int(32768))
    }

    // MARK: - opt-in check against the real Python catalog

    /// ``JAEGER_SETTINGS_CATALOG_JSON`` = path to a dump of
    /// ``core.settings.catalog.catalog(layout)`` from an isolated instance.
    func testDecodesRealCatalogDumpWhenProvided() async throws {
        guard let path = ProcessInfo.processInfo.environment["JAEGER_SETTINGS_CATALOG_JSON"] else {
            throw XCTSkip("Set JAEGER_SETTINGS_CATALOG_JSON to a real catalog dump")
        }
        let (store, backend) = makeStore()
        backend.catalogOverride = try Data(contentsOf: URL(fileURLWithPath: path))

        await store.loadSettingsCatalog()

        XCTAssertEqual(store.settingsLoad, .loaded)
        let all = store.settingsGroups.flatMap(\.settings)
        XCTAssertFalse(all.isEmpty)
        for secret in all where secret.type == "secret" {
            XCTAssertNotNil(secret.configured, "\(secret.path) lost its configured status")
        }
    }

    // MARK: - helpers

    private func makeStore() -> (SettingsStore, ScriptedSettingsBackend) {
        let backend = ScriptedSettingsBackend()
        return (SettingsStore(agent: AgentBridge.shared, backend: backend), backend)
    }

    private func setting(_ store: SettingsStore, _ path: String) -> Setting? {
        store.settingsGroups.flatMap(\.settings).first { $0.path == path }
    }

    private func current(_ store: SettingsStore, _ path: String) -> SettingValue? {
        setting(store, path)?.current
    }

    /// Every value ``path`` shows from now on, in publish order.
    private func record(_ store: SettingsStore, _ path: String) -> Recorder {
        let recorder = Recorder()
        recorder.cancellable = store.$settingsGroups.dropFirst().sink { groups in
            MainActor.assumeIsolated {
                if let v = groups.flatMap(\.settings).first(where: { $0.path == path })?.current {
                    recorder.values.append(v)
                }
            }
        }
        return recorder
    }

    /// Let already-started main-actor tasks run to their next suspension.
    private func settle() async {
        for _ in 0..<20 { await Task.yield() }
    }
}

@MainActor
private final class Recorder {
    var values: [SettingValue] = []
    var cancellable: AnyCancellable?
}

@MainActor
private final class Gate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        let pending = waiters
        waiters = []
        pending.forEach { $0.resume() }
    }
}

/// Behaves like the bridge's ``settings_catalog`` query and ``settings_set``
/// command over ``core/settings/catalog.py``, with hooks to hold a request.
@MainActor
private final class ScriptedSettingsBackend: SettingsBackend {
    private struct Field {
        let path: String
        let group: String
        let type: String
        let defaultValue: Any
        var stored: Any
        let restart: Bool
        var min: Double? = nil
    }

    private var fields: [Field] = [
        Field(path: "model.ctx", group: "model", type: "int",
              defaultValue: 2048, stored: 2048, restart: true, min: 512),
        Field(path: "model.extra_gguf_dirs", group: "model", type: "json",
              defaultValue: [String](), stored: [String](), restart: true),
        Field(path: "display.show_latency", group: "display", type: "bool",
              defaultValue: false, stored: false, restart: false),
        Field(path: "persona.greeting", group: "persona", type: "str",
              defaultValue: "", stored: "", restart: false),
        Field(path: "webhooks.secret", group: "webhooks", type: "secret",
              defaultValue: "", stored: "", restart: true),
    ]

    var queryError: String?
    var failGroupQueries = false
    var catalogOverride: Data?
    var replyErrorAfterWrite: String?
    var beforeSet: (@MainActor (String) async -> Void)?
    /// Runs after the catalog was read, before it is returned. ``group`` is
    /// nil for a full load, the group name for a read-back.
    var afterSnapshot: (@MainActor (String?) async -> Void)?
    private(set) var sets: [(path: String, value: SettingValue)] = []

    func setStored(_ path: String, _ value: Any) {
        if let i = fields.firstIndex(where: { $0.path == path }) { fields[i].stored = value }
    }

    func query(_ what: String, args: [String: any Sendable]) async -> QueryResult {
        let group = args["group"] as? String
        if let queryError { return QueryResult(ok: false, error: queryError, json: nil) }
        if failGroupQueries, group != nil {
            return QueryResult(ok: false, error: "bridge timed out", json: nil)
        }
        if let catalogOverride { return QueryResult(ok: true, error: nil, json: catalogOverride) }
        let snapshot = catalog(group: group)
        await afterSnapshot?(group)
        return QueryResult(ok: true, error: nil, json: snapshot)
    }

    func settingsSet(path: String, value: SettingValue) async -> QueryResult {
        sets.append((path, value))
        await beforeSet?(path)
        guard let i = fields.firstIndex(where: { $0.path == path }) else {
            return fail("unknown setting: '\(path)'")
        }
        let field = fields[i]
        let normalized: Any
        switch (field.type, value) {
        case ("int", .int(let n)): normalized = n
        case ("int", .string(let s)):
            guard let n = Int(s) else {
                return fail("invalid value for \(path): Input should be a valid integer")
            }
            normalized = n
        case ("bool", .bool(let b)): normalized = b
        case ("json", .string(let s)):
            guard let parsed = try? JSONSerialization.jsonObject(with: Data(s.utf8)) else {
                return fail("invalid JSON for \(path)")
            }
            normalized = parsed
        // Stand-in for a schema validator that normalizes text.
        case ("str", .string(let s)): normalized = s.trimmingCharacters(in: .whitespaces)
        case ("secret", .string(let s)): normalized = s
        default: return fail("invalid value for \(path)")
        }
        if let min = field.min, let n = normalized as? Int, Double(n) < min {
            return fail("invalid value for \(path): Input should be greater than or equal to \(Int(min))")
        }
        fields[i].stored = normalized
        if let replyErrorAfterWrite { return fail(replyErrorAfterWrite) }
        return ok(["restart_required": field.restart, "path": path,
                   "value": field.type == "secret" ? "" : normalized])
    }

    private func catalog(group: String?) -> Data {
        var grouped: [String: [[String: Any]]] = [:]
        for f in fields where group == nil || f.group == group {
            var d: [String: Any] = [
                "path": f.path, "label": f.path, "group": f.group, "type": f.type,
                "default": display(f.defaultValue, f.type),
                "current": display(f.stored, f.type),
                "description": "", "restart": f.restart, "advanced": false,
                "validation": f.min.map { ["min": $0] } ?? [:],
            ]
            if f.type == "secret" {
                d["default"] = ""
                d["current"] = ""
                d["configured"] = !((f.stored as? String) ?? "").isEmpty
            }
            grouped[f.group, default: []].append(d)
        }
        return try! JSONSerialization.data(withJSONObject: grouped)
    }

    private func display(_ value: Any, _ type: String) -> Any {
        guard type == "json" else { return value }
        let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }

    private func ok(_ data: [String: Any]) -> QueryResult {
        QueryResult(ok: true, error: nil, json: try! JSONSerialization.data(withJSONObject: data))
    }

    private func fail(_ error: String) -> QueryResult {
        QueryResult(ok: false, error: error, json: nil)
    }
}
