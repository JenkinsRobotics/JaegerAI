import XCTest
@testable import JaegerAI

final class NativePanelTests: XCTestCase {
    func testSchedulerPreservesPersistedState() throws {
        let jobs = try JSONDecoder().decode(CronCatalog.self, from: Data(#"{"jobs":[{"id":"job1","name":"Real job","enabled":false,"state":"paused","prompt":"Inspect files"}]}"#.utf8))
        XCTAssertEqual(jobs.jobs.first?.state, "paused")
        XCTAssertEqual(jobs.jobs.first?.enabled, false)
        XCTAssertThrowsError(try JSONDecoder().decode(CronCatalog.self, from: Data(#"{"error":"denied"}"#.utf8)))
    }
    func testTaskBoardUsesOwnerStatesAndActualRunHistory() throws {
        let data = Data(#"{"tasks":[{"task_id":"t1","goal":"Inspect","state":"failed","agent_id":"native:jaeger","runner":"native","error":"Tool failed","updated_at":12,"run_history":[{"run_id":"r1","status":"failed","error":"Tool failed"}]}]}"#.utf8)
        let task = try XCTUnwrap(JSONDecoder().decode(NativeTasks.self, from: data).tasks.first)
        XCTAssertFalse(task.editable)
        XCTAssertEqual(task.run_history.first?.status, "failed")
        XCTAssertEqual(task.error, "Tool failed")
        XCTAssertTrue(task.hasKnownBoardState)
        let unknown = try JSONDecoder().decode(NativeTask.self, from: Data(#"{"task_id":"u","goal":"Unknown work","state":"execution_unknown","agent_id":"worker","runner":"delegate:worker","updated_at":1,"run_history":[]}"#.utf8))
        XCTAssertFalse(unknown.hasKnownBoardState)
        XCTAssertFalse(unknown.editable)
    }
}
