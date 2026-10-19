import Foundation

struct CronCatalog: Decodable { let jobs: [CronRow] }
struct CronRow: Decodable, Identifiable {
    let id: String; let name: String?; let schedule_display: String?
    let enabled: Bool?; let state: String?; let last_status: String?
    let prompt: String?; let deliver: String?
}
struct NativeTask: Decodable, Identifiable {
    struct Run: Decodable { let run_id: String; let status: String; let error: String? }
    let task_id: String; let goal: String; let state: String
    let agent_id: String; let runner: String; let eta: String?
    let error: String?; let run_history: [Run]; let updated_at: Double
    var id: String { task_id }
    var editable: Bool { state == "paused" && run_history.isEmpty }
}
struct NativeTasks: Decodable { let tasks: [NativeTask] }
struct CronHistory: Decodable {
    struct Request: Decodable { let request_id: String; let status: String }
    let tasks: [NativeTask]; let requests: [Request]
}

/// All controls use the same authenticated Gateway as chat. No second runner or cookie transfer.
@MainActor
final class NativePanelClient {
    let gateway: GatewayClient
    init(gateway: GatewayClient = GatewayClient(baseURL: GatewayEndpoint.resolve(ProcessInfo.processInfo.environment))) {
        self.gateway = gateway
    }
    func get<T: Decodable>(_ path: String) async throws -> T {
        try JSONDecoder().decode(T.self, from: await gateway.request(path: path))
    }
    func mutate(_ path: String, body: [String: Any], method: String = "POST") async throws {
        _ = try await gateway.request(path: path, method: method, jsonData: JSONSerialization.data(withJSONObject: body))
    }
    func schedule(_ action: String, body: [String: Any], operationID: String) async throws {
        var values = body; values["operation_id"] = operationID
        do { try await mutate("v1/schedules/" + action, body: values) }
        catch let failure as GatewayClient.Failure where failure.statusCode != nil && failure.statusCode! < 500 {
            throw failure
        } catch {
            // Recover the original receipt; never repeat an uncertain write.
            struct Operation: Decodable { let status: String; let receipt: Receipt? }
            struct Receipt: Decodable { let ok: Bool; let error: String? }
            let result: Operation
            do { result = try await get("v1/control-operations/" + operationID) }
            catch { throw GatewayClient.Failure(message: "Action \(operationID) outcome unknown. Refresh and inspect current state before another action.") }
            if result.status == "settled", let receipt = result.receipt {
                if receipt.ok { return }
                throw GatewayClient.Failure(message: receipt.error ?? "Action failed.")
            }
            throw GatewayClient.Failure(message: "Action \(operationID) outcome unknown. Refresh and inspect current state before another action.")
        }
    }
}
