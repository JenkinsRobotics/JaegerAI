import XCTest
@testable import JaegerAI

@MainActor
final class TTSOwnershipTests: XCTestCase {
    @MainActor
    private final class Speech {
        var started: [String] = []
        var replies: [CheckedContinuation<TTSManager.SpeechResult, Never>] = []
        func speak(_ text: String, _ rate: Float?) async -> TTSManager.SpeechResult {
            started.append(text)
            return await withCheckedContinuation { replies.append($0) }
        }
        func finish(_ result: TTSManager.SpeechResult = .spoken) {
            replies.removeFirst().resume(returning: result)
        }
    }

    private func until(_ condition: () -> Bool) async {
        for _ in 0..<1000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("speech task did not reach expected state")
    }

    func testSpeakAndWaitShareOneSerialDrain() async {
        let fake = Speech()
        let manager = TTSManager(speech: fake.speak, stopSpeech: {})
        manager.speak("one")
        await until { fake.started.count == 1 }
        let second = Task { await manager.speakAndWait("two") }
        await Task.yield()
        XCTAssertEqual(fake.started, ["one"])
        XCTAssertTrue(manager.isSpeaking)
        fake.finish()
        await until { fake.started.count == 2 }
        XCTAssertTrue(manager.isSpeaking)
        fake.finish()
        let completed = await second.value
        XCTAssertTrue(completed)
        await until { !manager.isSpeaking }
    }

    func testStopDropsQueuedWorkAndLateFailureCannotOverwriteNewSpeech() async {
        let fake = Speech()
        let manager = TTSManager(speech: fake.speak, stopSpeech: {})
        manager.speak("old")
        await until { fake.started.count == 1 }
        manager.speak("discard")
        manager.stop()
        XCTAssertTrue(manager.isSpeaking) // Stop request does not acknowledge silence.
        let next = Task { await manager.speakAndWait("new") }
        fake.finish(.failed("stale failure"))
        await until { fake.started.count == 2 }
        XCTAssertEqual(fake.started, ["old", "new"])
        XCTAssertNil(manager.lastError)
        XCTAssertTrue(manager.isSpeaking)
        fake.finish()
        let completed = await next.value
        XCTAssertTrue(completed)
        await until { !manager.isSpeaking }
    }

    func testNewSpeechWaitsForStopDispatchBarrier() async {
        let fake = Speech()
        var release: CheckedContinuation<Void, Never>?
        let manager = TTSManager(speech: fake.speak, stopSpeech: {
            await withCheckedContinuation { release = $0 }
        })
        manager.speak("old")
        await until { fake.started.count == 1 }
        manager.stop()
        await until { release != nil }
        manager.speak("new")
        fake.finish()
        await Task.yield()
        XCTAssertEqual(fake.started, ["old"])
        release?.resume()
        await until { fake.started.count == 2 }
        fake.finish()
        await until { !manager.isSpeaking }
    }

    func testQueuedWaiterSettlesFalseOnStop() async {
        let fake = Speech()
        let manager = TTSManager(speech: fake.speak, stopSpeech: {})
        manager.speak("old")
        await until { fake.started.count == 1 }
        var enqueued = false
        let waiter = Task {
            enqueued = true
            return await manager.speakAndWait("queued")
        }
        await until { enqueued }
        manager.stop()
        fake.finish()
        let completed = await waiter.value
        XCTAssertFalse(completed)
        await until { !manager.isSpeaking }
        XCTAssertEqual(fake.started, ["old"])
    }
}
