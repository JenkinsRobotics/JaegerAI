// The new main screen's NativeHost (jaeger_ai/interfaces/ui chat/nativeHost.ts + platform/native.ts) contract.
import XCTest
@testable import JaegerShellCore

final class HostContractTests: XCTestCase {
    private func cmd(_ type: String, _ payload: [String: Any]) -> Result<BridgeCommand, BridgeError> {
        BridgeCommand.from(BridgeRequest(id: "1", type: type, payload: payload), home: "/Users/me",
                           fileExists: { $0 == "/Users/me/notes.md" })
    }

    func testEveryRequestTypeTheUIPostsIsImplemented() {
        let payloads: [String: [String: Any]] = [
            "open.external": ["url": "https://example.com/"], "open.file": ["path": "/Users/me/notes.md"],
            "clipboard.write": ["text": "hi"], "clipboard.read": [:], "mic.status": [:], "tts.status": [:],
            "notifications.navigationAck": ["id": "12345678-1234-4234-9234-123456789012"],
            "notifications.badge": ["state": "unknown"], "notify": ["title": "Owned fixture"],
        ]
        for type in HostContract.requestTypes {
            guard case .success(let command) = cmd(type, payloads[type] ?? [:]) else { return XCTFail("\(type) refused") }
            if case .notImplemented = command { XCTFail("\(type) is a stub") }
            XCTAssertEqual(command.name, type)
        }
    }

    func testOpenExternalAndFileValidation() {
        XCTAssertEqual(cmd("open.external", ["url": "https://example.com/"]).successValue, .openExternal(URL(string: "https://example.com/")!))
        for bad in ["javascript:alert(1)", "file:///etc/hosts", "http://", 7] as [Any] {
            XCTAssertNotNil(cmd("open.external", ["url": bad]).failureValue, "\(bad)")
        }
        XCTAssertEqual(cmd("open.file", ["path": "/Users/me/notes.md"]).successValue, .openFile(URL(fileURLWithPath: "/Users/me/notes.md")))
        for bad in ["/etc/hosts", "/Users/me/missing.md", "relative.md", "/Users/me/../other/x"] {
            XCTAssertNotNil(cmd("open.file", ["path": bad]).failureValue, bad)
        }
    }

    func testClipboardWriteBounds() {
        XCTAssertEqual(cmd("clipboard.write", ["text": ""]).successValue, .clipboardWrite(""))
        XCTAssertNotNil(cmd("clipboard.write", ["text": 5]).failureValue)
        XCTAssertNotNil(cmd("clipboard.write", ["text": String(repeating: "x", count: 1_000_001)]).failureValue)
    }

    func testEventTypesIncludeTheOnesTheUIListensFor() {
        XCTAssertEqual(Set(HostContract.eventTypes), ["window.visibility", "hotkey", "appearance.changed", "notification.open"])
    }

    func testMainScreenOverrideKeys() {
        XCTAssertEqual(StartURL.mainScreenEnvValue(["JAEGER_SHELL_UI_URL": "http://127.0.0.1:18800/", "JAEGER_SHELL_WEBUI_URL": "http://127.0.0.1:18790/"]),
                       "http://127.0.0.1:18800/")
        XCTAssertEqual(StartURL.mainScreenEnvValue(["JAEGER_SHELL_WEBUI_URL": "http://127.0.0.1:18790/"]), "http://127.0.0.1:18790/")
        XCTAssertNil(StartURL.mainScreenEnvValue([:]))
        // default main screen = the Jaeger WebUI (8790); the gateway origin 401s on `/`
        let r = StartURL.resolve(fallback: StartURL.defaultMainScreen, envValue: nil, defaultsValue: nil, isDevBuild: true)
        XCTAssertEqual(r.url.absoluteString, "http://127.0.0.1:8790/?host=macos")
    }
}
