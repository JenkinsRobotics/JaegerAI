import Foundation

enum AppConfig {
    static let privacyPolicyURL = URL(staticString: "https://www.uzairansar.com/hermes-mobile/privacy")
    static let supportURL = URL(staticString: "https://www.uzairansar.com/hermes-mobile")
}

extension URL {
    init(staticString string: StaticString) {
        let value = string.withUTF8Buffer { String(decoding: $0, as: UTF8.self) }
        guard let url = URL(string: value) else {
            preconditionFailure("Invalid static URL literal: \(value)")
        }
        self = url
    }
}
