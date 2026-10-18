import XCTest
@testable import JaegerShellCore

final class VoiceTests: XCTestCase {
    func testTTSText() {
        XCTAssertEqual(TTSText.plainForSpeech("**Hello** `code` [link](http://x)"), "Hello code link")
        XCTAssertEqual(TTSText.plainForSpeech("# Title"), "Title")
        XCTAssertEqual(TTSText.plainForSpeech("Hi. There"), "Hi.  There")
        XCTAssertEqual(TTSText.plainForSpeech("```\n```"), "")
    }
    func testAudioMath() {
        XCTAssertEqual(AudioMath.mixToMono([[1, 0], [0, 1]]), [0.5, 0.5])
        XCTAssertEqual(AudioMath.mixToMono([[0.25, -0.25]]), [0.25, -0.25])
        XCTAssertEqual(AudioMath.mixToMono([]), [])
        XCTAssertEqual(AudioMath.rms([]), 0)
        XCTAssertEqual(AudioMath.rms([0.5, -0.5]), 0.5, accuracy: 1e-6)
    }
    func testVoiceCatalog() {
        let installed: Set<String> = ["com.apple.voice.compact.en-US.Samantha", "com.apple.voice.compact.en-US.Alex"]
        XCTAssertEqual(VoiceCatalog.resolve("female", installed: installed), "com.apple.voice.compact.en-US.Samantha")
        XCTAssertEqual(VoiceCatalog.resolve("Male", installed: installed), "com.apple.voice.compact.en-US.Alex")
        XCTAssertEqual(VoiceCatalog.resolve("com.apple.voice.compact.en-US.Alex", installed: installed), "com.apple.voice.compact.en-US.Alex")
        XCTAssertNil(VoiceCatalog.resolve("robot", installed: installed))
        XCTAssertNil(VoiceCatalog.resolve(nil, installed: installed))
    }
}
