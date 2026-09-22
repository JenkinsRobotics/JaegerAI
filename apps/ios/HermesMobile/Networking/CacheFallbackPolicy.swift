import Foundation

enum CacheFallbackPolicy {
    static func shouldUseCache(for error: Error) -> Bool {
        switch error {
        case APIError.network(let underlying):
            return isConnectivityError(underlying)
        case APIError.http(let statusCode, _):
            return isTransientUnavailableStatus(statusCode)
        default:
            return isConnectivityError(error)
        }
    }

    private static func isConnectivityError(_ error: Error) -> Bool {
        guard let urlError = error as? URLError else { return false }

        switch urlError.code {
        case .notConnectedToInternet,
             .networkConnectionLost,
             .cannotConnectToHost,
             .dnsLookupFailed,
             .cannotFindHost,
             .dataNotAllowed,
             .timedOut:
            return true
        default:
            return false
        }
    }

    private static func isTransientUnavailableStatus(_ statusCode: Int) -> Bool {
        switch statusCode {
        case 408, 502, 503, 504:
            return true
        default:
            return false
        }
    }
}
