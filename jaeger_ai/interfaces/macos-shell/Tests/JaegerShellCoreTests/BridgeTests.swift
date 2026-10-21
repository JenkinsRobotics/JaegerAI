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
        XCTAssertEqual(cmd("mic.start").successValue, .micStart(mode: "dictation"))
        XCTAssertEqual(cmd("mic.start", ["mode": "push-to-talk"]).successValue, .micStart(mode: "push-to-talk"))
        XCTAssertNotNil(cmd("mic.start", ["mode": "always-on"]).failureValue)
        XCTAssertNotNil(cmd("mic.start", ["mode": 1]).failureValue)
        XCTAssertEqual(cmd("mic.stop").successValue, .micStop)
        XCTAssertEqual(cmd("voice.status").successValue, .voiceStatus)
        XCTAssertEqual(cmd("tts.speak", ["text": "**Hi**", "voice": "female"]).successValue, .ttsSpeak(text: "**Hi**", voice: "female"))
        XCTAssertNotNil(cmd("tts.speak", ["text": ""]).failureValue)
        XCTAssertNotNil(cmd("tts.speak", ["text": "```\n```"]).failureValue)
        XCTAssertNotNil(cmd("tts.speak", ["text": "hi", "voice": 3]).failureValue)
        XCTAssertNotNil(cmd("tts.speak", ["text": String(repeating: "a", count: 10001)]).failureValue)
        XCTAssertEqual(cmd("tts.stop").successValue, .ttsStop)
        XCTAssertEqual(cmd("notify", ["title": "Hi", "body": "there"]).successValue, .notify(title: "Hi", body: "there", sessionId: nil))
        XCTAssertEqual(cmd("notify", ["title": "Hi", "session_id": "owned:home"]).successValue, .notify(title: "Hi", body: "", sessionId: "owned:home"))
        for invalid in ["https://example.com", "../other", "owned\nother", String(repeating: "x", count: 257)] {
            XCTAssertNotNil(cmd("notify", ["title": "Hi", "session_id": invalid]).failureValue)
        }
        XCTAssertEqual(cmd("notifications.navigation").successValue, .notificationNavigation)
        XCTAssertNotNil(cmd("notify", [:]).failureValue)
        XCTAssertEqual(cmd("notifications.status").successValue, .notificationStatus)
        XCTAssertEqual(BridgeCommand.notificationStatus.name, "notifications.status")
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

    func testFilePickPanelMessage() {
        XCTAssertEqual(FilePickOptions(multiple: true, maxFiles: 8, maxBytes: 20 * 1024 * 1024).panelMessage, "Up to 8 files, 20 MB each")
        XCTAssertEqual(FilePickOptions(multiple: false, maxBytes: 5 * 1024 * 1024).panelMessage, "Up to 1 file, 5 MB each")
        XCTAssertEqual(FilePickOptions(multiple: true).panelMessage, "")
    }

    func testFilePickOptions() {
        func parse(_ p: [String: Any]) -> FilePickOptions? { try? FilePickOptions.parse(p).get() }
        XCTAssertEqual(parse([:]), FilePickOptions(multiple: false, maxFiles: 1, maxBytes: nil, accept: []))
        XCTAssertEqual(parse(["multiple": true])?.maxFiles, FilePickOptions.maxFilesCap)
        XCTAssertEqual(parse(["multiple": true, "maxFiles": 8, "maxBytes": 20_971_520, "accept": ["Image/*", ".PDF"]]),
                       FilePickOptions(multiple: true, maxFiles: 8, maxBytes: 20_971_520, accept: ["image/*", ".pdf"]))
        XCTAssertEqual(parse(["multiple": true, "maxFiles": 500])?.maxFiles, FilePickOptions.maxFilesCap)
        XCTAssertNil(parse(["multiple": "yes"]))
        XCTAssertNil(parse(["maxFiles": 0]))
        XCTAssertNil(parse(["maxBytes": 1.5]))
        XCTAssertNil(parse(["maxBytes": true]))
        XCTAssertNil(parse(["accept": "image/*"]))
        XCTAssertNil(parse(["accept": [""]]))
        let req = try! BridgeRequest.parse(["id": "1", "type": "files.pick", "payload": ["multiple": true]]).get()
        XCTAssertEqual(try BridgeCommand.from(req, home: "/Users/x", fileExists: { _ in true }).get().name, "files.pick")
    }

    func testFilePickSelect() {
        let png = PickedFile(path: "/Users/x/a.png", name: "a.png", size: 10, mimeType: "image/png")
        let pdf = PickedFile(path: "/Users/x/b.pdf", name: "b.pdf", size: 30, mimeType: "application/pdf")
        let big = PickedFile(path: "/Users/x/c.mov", name: "c.mov", size: 9_000, mimeType: "video/quicktime")
        let dir = PickedFile(path: "/Users/x/d", name: "d", size: 0, mimeType: "", isRegularFile: false)
        let all = FilePickOptions(multiple: true)
        XCTAssertEqual(FilePick.select([png, pdf, big, dir], all), [png, pdf, big])
        XCTAssertEqual(FilePick.select([png, pdf, big], FilePickOptions(multiple: true, maxBytes: 100)), [png, pdf])
        XCTAssertEqual(FilePick.select([png, pdf, big], FilePickOptions(multiple: true, maxFiles: 1)), [png])
        XCTAssertEqual(FilePick.select([png, pdf, big], FilePickOptions(multiple: false)), [png])
        XCTAssertEqual(FilePick.select([png, pdf, big], FilePickOptions(multiple: true, accept: ["image/*"])), [png])
        XCTAssertEqual(FilePick.select([png, pdf, big], FilePickOptions(multiple: true, accept: [".pdf", "video/quicktime"])), [pdf, big])
        XCTAssertEqual(FilePick.select([], all), [])
        let reply = png.reply
        XCTAssertEqual(reply["uri"] as? String, "file:///Users/x/a.png")
        XCTAssertEqual(Set(reply.keys), ["path", "name", "size", "mimeType", "uri"])
    }
}

extension Result {
    var successValue: Success? { if case .success(let v) = self { return v }; return nil }
    var failureValue: Failure? { if case .failure(let e) = self { return e }; return nil }

}
