import XCTest
import AppIntents
@testable import HermesMobile

/// Covers the New Chat App Intent plumbing (issue #337): the parameter-less deep-link URL,
/// its round-trip detection, the router bridge an intent writes to, and the intent itself.
final class AppIntentNewChatTests: XCTestCase {

    // `AppIntentRouter` is a shared singleton, so reset its pending link around every
    // test. Doing it in setUp/tearDown (rather than inline) guarantees a clean slate
    // before each test and cleanup after every exit path — including a failed assertion
    // or a thrown error mid-test — so router state can't leak between tests.
    override func setUp() async throws {
        try await super.setUp()
        await MainActor.run { AppIntentRouter.shared.pendingDeepLink = nil }
    }

    override func tearDown() async throws {
        await MainActor.run { AppIntentRouter.shared.pendingDeepLink = nil }
        try await super.tearDown()
    }

    func testNewChatURLUsesNewChatHostOnTheAppScheme() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatURL)
        XCTAssertEqual(url.scheme, HermesDeepLink.scheme)
        XCTAssertEqual(url.host, HermesDeepLink.newChatHost)
    }

    func testIsNewChatURLAcceptsItsOwnURL() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatURL)
        XCTAssertTrue(HermesDeepLink.isNewChatURL(url))
    }

    func testIsNewChatURLIsCaseInsensitiveOnHost() throws {
        let url = try XCTUnwrap(URL(string: "\(HermesDeepLink.scheme)://New-Chat"))
        XCTAssertTrue(HermesDeepLink.isNewChatURL(url))
    }

    func testSessionURLIsNotANewChatURL() throws {
        let session = try XCTUnwrap(HermesDeepLink.sessionURL(sessionID: "abc123"))
        XCTAssertFalse(HermesDeepLink.isNewChatURL(session))
    }

    func testNewChatURLDoesNotParseAsASessionID() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatURL)
        XCTAssertNil(HermesDeepLink.sessionID(from: url))
    }

    func testForeignSchemeIsNotANewChatURL() throws {
        let url = try XCTUnwrap(URL(string: "https://new-chat"))
        XCTAssertFalse(HermesDeepLink.isNewChatURL(url))
    }

    @MainActor
    func testRouterRecordsDeepLink() {
        let router = AppIntentRouter.shared
        router.requestDeepLink(HermesDeepLink.newChatURL)
        XCTAssertEqual(router.pendingDeepLink, HermesDeepLink.newChatURL)
    }

    @MainActor
    func testRouterIgnoresNilDeepLink() {
        let router = AppIntentRouter.shared
        router.requestDeepLink(nil)
        XCTAssertNil(router.pendingDeepLink)
    }

    @MainActor
    func testNewChatIntentQueuesTheNewChatDeepLink() async throws {
        let router = AppIntentRouter.shared
        _ = try await NewChatIntent().perform()
        XCTAssertEqual(router.pendingDeepLink, HermesDeepLink.newChatURL)
    }

    func testIntentOpensAppWhenRun() {
        XCTAssertTrue(NewChatIntent.openAppWhenRun)
    }

    // MARK: - New Chat with Voice (issue #338)

    func testNewChatVoiceURLUsesVoiceHostOnTheAppScheme() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatVoiceURL)
        XCTAssertEqual(url.scheme, HermesDeepLink.scheme)
        XCTAssertEqual(url.host, HermesDeepLink.newChatVoiceHost)
    }

    func testIsNewChatVoiceURLAcceptsItsOwnURL() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatVoiceURL)
        XCTAssertTrue(HermesDeepLink.isNewChatVoiceURL(url))
    }

    func testIsNewChatVoiceURLIsCaseInsensitiveOnHost() throws {
        let url = try XCTUnwrap(URL(string: "\(HermesDeepLink.scheme)://New-Chat-Voice"))
        XCTAssertTrue(HermesDeepLink.isNewChatVoiceURL(url))
    }

    func testVoiceAndPlainNewChatURLsDoNotAlias() throws {
        let voiceURL = try XCTUnwrap(HermesDeepLink.newChatVoiceURL)
        let plainURL = try XCTUnwrap(HermesDeepLink.newChatURL)
        // The two intents must route distinctly: a voice URL is not a plain new-chat URL,
        // and vice versa.
        XCTAssertFalse(HermesDeepLink.isNewChatURL(voiceURL))
        XCTAssertFalse(HermesDeepLink.isNewChatVoiceURL(plainURL))
    }

    func testNewChatVoiceURLDoesNotParseAsASessionID() throws {
        let url = try XCTUnwrap(HermesDeepLink.newChatVoiceURL)
        XCTAssertNil(HermesDeepLink.sessionID(from: url))
    }

    func testSessionURLIsNotAVoiceURL() throws {
        let session = try XCTUnwrap(HermesDeepLink.sessionURL(sessionID: "abc123"))
        XCTAssertFalse(HermesDeepLink.isNewChatVoiceURL(session))
    }

    func testForeignSchemeIsNotAVoiceURL() throws {
        let url = try XCTUnwrap(URL(string: "https://new-chat-voice"))
        XCTAssertFalse(HermesDeepLink.isNewChatVoiceURL(url))
    }

    @MainActor
    func testNewChatVoiceIntentQueuesTheVoiceDeepLink() async throws {
        let router = AppIntentRouter.shared
        _ = try await NewChatVoiceIntent().perform()
        XCTAssertEqual(router.pendingDeepLink, HermesDeepLink.newChatVoiceURL)
    }

    func testVoiceIntentOpensAppWhenRun() {
        XCTAssertTrue(NewChatVoiceIntent.openAppWhenRun)
    }

    func testNewChatRequestDefaultsToVoiceOff() {
        XCTAssertFalse(NewChatRequest().autoStartsVoiceInput)
    }

    func testNewChatRequestCarriesVoiceFlag() {
        XCTAssertTrue(NewChatRequest(autoStartsVoiceInput: true).autoStartsVoiceInput)
    }
}
