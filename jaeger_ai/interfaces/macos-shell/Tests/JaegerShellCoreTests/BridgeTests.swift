import XCTest
@testable import JaegerShellCore

final class BridgeTests: XCTestCase {
    let allowed = LoopbackOrigin(port: 18790)
    let home = "/Users/jaeger-test-home"

    private func req(_ type: String, _ payload: [String: Any] = [:]) -> BridgeRequest {
        guard case .success(let r) = BridgeRequest.parse(["id": "1", "type": type, "payload": payload]) else {
            fatalError("parse failed")
        }
        return r
    }
    private func cmd(_ type: String, _ payload: [String: Any] = [:], exists: Bool = true) -> Result<BridgeCommand, BridgeError> {
        BridgeCommand.from(req(type, payload), home: home, fileExists: { _ in exists })
    }

    func testOriginPolicy() {
        XCTAssertTrue(BridgeOriginPolicy.accepts(.init(isMainFrame: true, scheme: "http", host: "127.0.0.1", port: 18790), allowed: allowed))
        XCTAssertFalse(BridgeOriginPolicy.accepts(.init(isMainFrame: false, scheme: "http", host: "127.0.0.1", port: 18790), allowed: allowed))
        XCTAssertFalse(BridgeOriginPolicy.accepts(.init(isMainFrame: true, scheme: "http", host: "127.0.0.1", port: 18791), allowed: allowed))
        XCTAssertFalse(BridgeOriginPolicy.accepts(.init(isMainFrame: true, scheme: "https", host: "127.0.0.1", port: 18790), allowed: allowed))
        XCTAssertFalse(BridgeOriginPolicy.accepts(.init(isMainFrame: true, scheme: "http", host: "localhost", port: 18790), allowed: allowed))
        XCTAssertFalse(BridgeOriginPolicy.accepts(.init(isMainFrame: true, scheme: "", host: "", port: 0), allowed: allowed))
    }

    func testWindowChromePolicy() {
        let main = BridgeFrame(isMainFrame: true, scheme: "http", host: "127.0.0.1", port: 18790)
        XCTAssertTrue(WindowChromePolicy.accepts(main, allowed: allowed))
        XCTAssertFalse(WindowChromePolicy.accepts(main, allowed: nil))  // fails closed
        XCTAssertFalse(WindowChromePolicy.accepts(.init(isMainFrame: false, scheme: "http", host: "127.0.0.1", port: 18790), allowed: allowed))
        XCTAssertFalse(WindowChromePolicy.accepts(.init(isMainFrame: true, scheme: "http", host: "127.0.0.1", port: 18791), allowed: allowed))
    }

    func testParse() {
        XCTAssertEqual(BridgeRequest.parse("nope").failureValue, .badMessage)
        XCTAssertEqual(BridgeRequest.parse(["type": "app.info"]).failureValue, .badMessage)
        XCTAssertEqual(BridgeRequest.parse(["id": "1", "type": "app.info", "payload": "x"]).failureValue, .badMessage)
        XCTAssertEqual(req("app.info").type, "app.info")
    }

    func testCommands() {
        XCTAssertEqual(cmd("window.hide").successValue, .windowHide)
        XCTAssertEqual(cmd("window.open").successValue, .windowShow)
        XCTAssertEqual(cmd("app.info").successValue, .appInfo)
        XCTAssertEqual(cmd("bogus").failureValue, .unknownType("bogus"))
        XCTAssertEqual(cmd("mic.start").successValue, .notImplemented("mic.start"))
        XCTAssertEqual(cmd("notify", ["title": "Hi", "body": "there"]).successValue, .notify(title: "Hi", body: "there"))
        XCTAssertNotNil(cmd("notify", [:]).failureValue)
    }

    func testStrictBools() {
        XCTAssertEqual(cmd("launchAtLogin.set", ["enabled": true]).successValue, .launchAtLoginSet(true))
        XCTAssertNotNil(cmd("launchAtLogin.set", ["enabled": 1]).failureValue)
        XCTAssertNotNil(cmd("launchAtLogin.set", ["enabled": "true"]).failureValue)
        XCTAssertEqual(cmd("window.setPinned", ["pinned": false]).successValue, .windowSetPinned(false))
    }

    func testLinks() {
        XCTAssertEqual(cmd("link.open", ["url": "https://example.com/a"]).successValue, .linkOpen(URL(string: "https://example.com/a")!))
        XCTAssertNotNil(cmd("link.open", ["url": "http://127.0.0.1:8790/"]).successValue)
        for bad in ["file:///etc/hosts", "javascript:alert(1)", "mailto:a@b.c", "https://", "https://u:p@example.com/", "/relative"] {
            XCTAssertNotNil(cmd("link.open", ["url": bad]).failureValue, bad)
        }
    }

    func testReveal() {
        XCTAssertEqual(cmd("file.reveal", ["path": "\(home)/a/../b.txt"]).successValue, .fileReveal(URL(fileURLWithPath: "\(home)/b.txt")))
        XCTAssertNotNil(cmd("file.reveal", ["path": "\(home)/../other/x"]).failureValue)
        XCTAssertNotNil(cmd("file.reveal", ["path": "/etc/hosts"]).failureValue)
        XCTAssertNotNil(cmd("file.reveal", ["path": "b.txt"]).failureValue)
        XCTAssertNotNil(cmd("file.reveal", ["path": home]).failureValue)
        XCTAssertNotNil(cmd("file.reveal", ["path": "\(home)/b.txt"], exists: false).failureValue)
    }

    func testEventScript() throws {
        let js = try XCTUnwrap(BridgeScript.event(["type": "reply", "id": "1", "ok": true, "result": ["t": "a\u{2028}b"]]))
        XCTAssertTrue(js.hasPrefix("window.dispatchEvent(new CustomEvent(\"jaeger:native\",{detail:"))
        XCTAssertFalse(js.contains("\u{2028}"))
        let start = try XCTUnwrap(js.range(of: "{detail:")).upperBound
        let end = try XCTUnwrap(js.range(of: "}));", options: .backwards)).lowerBound
        let json = String(js[start..<end])
        XCTAssertNotNil(try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any])
        XCTAssertNil(BridgeScript.event(["bad": Date()]))
        XCTAssertTrue(BridgeScript.userScript.contains("data-jaeger-host"))
    }
}

extension Result {
    var successValue: Success? { if case .success(let v) = self { return v }; return nil }
    var failureValue: Failure? { if case .failure(let e) = self { return e }; return nil }
}
