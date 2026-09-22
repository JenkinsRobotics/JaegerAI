import Foundation

extension APIClient {
    func memory() async throws -> MemoryResponse {
        try await send(endpoint: .memory, method: "GET")
    }

    func writeMemory(section: MemorySection, content: String) async throws -> MemoryWriteResponse {
        try await send(
            endpoint: .memoryWrite,
            method: "POST",
            body: MemoryWriteRequest(section: section, content: content)
        )
    }
}

private struct MemoryWriteRequest: Encodable {
    let section: MemorySection
    let content: String
}

