import XCTest
@testable import HermesMobile

/// Request construction + tolerant decoding for the read-only workspace-git endpoints
/// (issue #312, Slice A). Mirrors `APIClientWorkspaceFileTests`.
final class APIClientGitTests: APIClientTestCase {

    private func query(_ request: URLRequest) throws -> [String: String?] {
        let components = URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)
        return Dictionary(uniqueKeysWithValues: (components?.queryItems ?? []).map { ($0.name, $0.value) })
    }

    private func errorResponse(_ json: String, status: Int, for request: URLRequest) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(json.utf8))
    }

    private func jsonBody(_ request: URLRequest) throws -> [String: Any] {
        let data = try XCTUnwrap(apiTestBodyData(from: request))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    // MARK: - git-info

    func testGitInfoBuildsExpectedQueryAndDecodes() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git-info")
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(try self.query(request)["session_id"], "abc123")

            return apiTestJSONResponse("""
            {
              "git": {
                "branch": "main",
                "dirty": 3,
                "modified": 2,
                "untracked": 1,
                "ahead": 2,
                "behind": 0,
                "is_git": true
              }
            }
            """, for: request)
        }

        let response = try await client.gitInfo(sessionID: "abc123")
        let info = try XCTUnwrap(response.git)

        XCTAssertEqual(info.branch, "main")
        XCTAssertEqual(info.dirty, 3)
        XCTAssertEqual(info.modified, 2)
        XCTAssertEqual(info.untracked, 1)
        XCTAssertEqual(info.ahead, 2)
        XCTAssertEqual(info.behind, 0)
        XCTAssertEqual(info.isGit, true)
    }

    func testGitInfoDecodesNullGitForNonRepository() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git-info")
            return apiTestJSONResponse(#"{"git": null}"#, for: request)
        }

        let response = try await client.gitInfo(sessionID: "abc123")
        XCTAssertNil(response.git)
    }

    // MARK: - git/status

    func testGitStatusBuildsExpectedQueryAndDecodesFilesAndTotals() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/status")
            XCTAssertEqual(try self.query(request)["session_id"], "abc123")

            return apiTestJSONResponse("""
            {
              "git": {
                "is_git": true,
                "branch": "feature/foo",
                "upstream": "origin/feature/foo",
                "ahead": 1,
                "behind": 2,
                "totals": {"changed": 2, "staged": 1, "unstaged": 1, "untracked": 1, "conflicts": 0},
                "files": [
                  {
                    "path": "Sources/App.swift", "old_path": null, "workspace_path": "Sources/App.swift",
                    "status": "M", "staged": false, "unstaged": true, "untracked": false,
                    "ignored": false, "conflict": false, "additions": 10, "deletions": 4, "binary": false
                  },
                  {
                    "path": "New.swift", "old_path": null, "workspace_path": "New.swift",
                    "status": "??", "staged": false, "unstaged": false, "untracked": true,
                    "ignored": false, "conflict": false, "additions": 0, "deletions": 0, "binary": false
                  },
                  {
                    "path": ".DS_Store", "old_path": null, "workspace_path": ".DS_Store",
                    "status": "Ignored", "staged": false, "unstaged": false, "untracked": false,
                    "ignored": true, "conflict": false, "additions": 0, "deletions": 0, "binary": false
                  }
                ],
                "truncated": false,
                "noise_filtering": {"enabled": true}
              }
            }
            """, for: request)
        }

        let statusResponse = try await client.gitStatus(sessionID: "abc123")
        let status = try XCTUnwrap(statusResponse.git)

        XCTAssertEqual(status.isGit, true)
        XCTAssertEqual(status.branch, "feature/foo")
        XCTAssertEqual(status.upstream, "origin/feature/foo")
        XCTAssertEqual(status.ahead, 1)
        XCTAssertEqual(status.behind, 2)
        XCTAssertEqual(status.totals?.changed, 2)
        XCTAssertEqual(status.files?.count, 3, "Raw files include the ignored entry.")

        // Ignored files are filtered from the tracked list and counts/totals.
        XCTAssertEqual(status.trackedFiles.count, 2)
        XCTAssertEqual(status.changedCount, 2)
        XCTAssertEqual(status.totalAdditions, 10)
        XCTAssertEqual(status.totalDeletions, 4)
        XCTAssertFalse(status.trackedFiles.contains { $0.ignored == true })

        // Change kind is derived from the booleans.
        XCTAssertEqual(status.trackedFiles[0].changeKind, .modified)
        XCTAssertEqual(status.trackedFiles[1].changeKind, .untracked)
        XCTAssertEqual(status.trackedFiles[0].fileName, "App.swift")
        XCTAssertEqual(status.trackedFiles[0].parentDirectory, "Sources")
    }

    func testGitStatusDecodesNonRepository() async throws {
        let client = makeClient { request in
            apiTestJSONResponse(#"{"git": {"is_git": false}}"#, for: request)
        }

        let statusResponse = try await client.gitStatus(sessionID: "abc123")
        let status = try XCTUnwrap(statusResponse.git)
        XCTAssertEqual(status.isGit, false)
        XCTAssertTrue(status.trackedFiles.isEmpty)
        XCTAssertEqual(status.changedCount, 0)
    }

    func testGitStatusToleratesMissingFieldsAndUnknownKeys() async throws {
        let client = makeClient { request in
            apiTestJSONResponse("""
            {
              "git": {
                "is_git": true,
                "branch": "main",
                "files": [
                  {"path": "a.txt", "status": "A", "staged": true, "future_field": 99}
                ],
                "totally_new_key": {"nested": true}
              }
            }
            """, for: request)
        }

        let statusResponse = try await client.gitStatus(sessionID: "abc123")
        let status = try XCTUnwrap(statusResponse.git)
        XCTAssertEqual(status.branch, "main")
        XCTAssertNil(status.totals)
        XCTAssertNil(status.truncated)
        let file = try XCTUnwrap(status.files?.first)
        XCTAssertEqual(file.path, "a.txt")
        XCTAssertNil(file.additions)
        XCTAssertEqual(file.changeKind, .added)
        // Truncation defaults to "not truncated" and changedCount falls back to file count.
        XCTAssertEqual(status.changedCount, 1)
    }

    func testGitStatusFiltersIgnoredFilesByStatusString() async throws {
        let client = makeClient { request in
            apiTestJSONResponse("""
            {
              "git": {
                "is_git": true,
                "branch": "main",
                "files": [
                  {"path": ".DS_Store", "status": "Ignored", "additions": 0, "deletions": 0}
                ]
              }
            }
            """, for: request)
        }

        let statusResponse = try await client.gitStatus(sessionID: "abc123")
        let status = try XCTUnwrap(statusResponse.git)
        XCTAssertEqual(status.files?.count, 1)
        XCTAssertEqual(status.trackedFiles.count, 0)
        XCTAssertEqual(status.changedCount, 0)
        XCTAssertEqual(status.files?.first?.changeKind, .ignored)
    }

    func testGitStatusTruncatedFlagDecodes() async throws {
        let client = makeClient { request in
            apiTestJSONResponse("""
            { "git": { "is_git": true, "branch": "main", "files": [], "truncated": true,
              "totals": {"changed": 500} } }
            """, for: request)
        }

        let statusResponse = try await client.gitStatus(sessionID: "abc123")
        let status = try XCTUnwrap(statusResponse.git)
        XCTAssertEqual(status.truncated, true)
        XCTAssertEqual(status.changedCount, 500)
    }

    // MARK: - git/branches

    func testGitBranchesBuildsExpectedQueryAndDecodes() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/branches")
            XCTAssertEqual(try self.query(request)["session_id"], "abc123")

            return apiTestJSONResponse("""
            {
              "branches": {
                "is_git": true,
                "current": "main",
                "detached": false,
                "head": "main",
                "local": [
                  {
                    "name": "main",
                    "sha": "abc1234",
                    "updated": 1782080000,
                    "updated_relative": "2 hours ago",
                    "author": "Uzair",
                    "subject": "Latest local commit",
                    "upstream": "origin/main",
                    "ahead": 0,
                    "behind": 0
                  },
                  {
                    "name": "dev",
                    "sha": "def5678",
                    "updated": 1782070000,
                    "updated_relative": "5 hours ago",
                    "author": "Uzair",
                    "subject": "Dev branch",
                    "upstream": "",
                    "ahead": 0,
                    "behind": 0,
                    "future_field": true
                  }
                ],
                "remote": [
                  {
                    "name": "origin/main",
                    "sha": "abc1234",
                    "updated": 1782080000,
                    "updated_relative": "2 hours ago",
                    "author": "Uzair",
                    "subject": "Latest remote commit",
                    "upstream": "",
                    "ahead": 0,
                    "behind": 0
                  }
                ],
                "upstream": "origin/main",
                "ahead": 0,
                "behind": 0
              }
            }
            """, for: request)
        }

        let branchesResponse = try await client.gitBranches(sessionID: "abc123")
        let branches = try XCTUnwrap(branchesResponse.branches)
        XCTAssertEqual(branches.current, "main")
        XCTAssertEqual(branches.local?.map(\.name), ["main", "dev"])
        XCTAssertEqual(branches.local?.first?.sha, "abc1234")
        XCTAssertEqual(branches.local?.first?.updatedRelative, "2 hours ago")
        XCTAssertEqual(branches.local?.first?.upstream, "origin/main")
        XCTAssertEqual(branches.local?.first?.ahead, 0)
        XCTAssertEqual(branches.local?.first?.behind, 0)
        XCTAssertEqual(branches.remote?.map(\.name), ["origin/main"])
        XCTAssertEqual(branches.detached, false)
    }

    // MARK: - git/diff

    func testGitDiffBuildsExpectedQueryWithKindAndDecodes() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/diff")
            let q = try self.query(request)
            XCTAssertEqual(q["session_id"], "abc123")
            XCTAssertEqual(q["path"], "Sources/App.swift")
            XCTAssertEqual(q["kind"], "staged")

            return apiTestJSONResponse("""
            {
              "diff": {
                "path": "Sources/App.swift",
                "kind": "staged",
                "binary": false,
                "too_large": false,
                "additions": 2,
                "deletions": 1,
                "diff": "@@ -1,2 +1,3 @@\\n context\\n-old\\n+new\\n+added\\n"
              }
            }
            """, for: request)
        }

        let diffResponse = try await client.gitDiff(sessionID: "abc123", path: "Sources/App.swift", kind: "staged")
        let diff = try XCTUnwrap(diffResponse.diff)
        XCTAssertEqual(diff.path, "Sources/App.swift")
        XCTAssertEqual(diff.kind, "staged")
        XCTAssertEqual(diff.binary, false)
        XCTAssertEqual(diff.tooLarge, false)
        XCTAssertEqual(diff.additions, 2)
        XCTAssertEqual(diff.deletions, 1)
        XCTAssertTrue(diff.diff?.contains("+added") == true)
    }

    func testGitDiffDefaultsKindToUnstaged() async throws {
        let client = makeClient { request in
            XCTAssertEqual(try self.query(request)["kind"], "unstaged")
            return apiTestJSONResponse(#"{"diff": {"path": "a.txt", "kind": "unstaged", "diff": ""}}"#, for: request)
        }

        _ = try await client.gitDiff(sessionID: "abc123", path: "a.txt")
    }

    func testGitDiffDecodesBinaryAndTooLarge() async throws {
        let binaryClient = makeClient { request in
            apiTestJSONResponse("""
            {"diff": {"path": "logo.png", "kind": "unstaged", "binary": true, "too_large": false,
              "additions": 0, "deletions": 0, "diff": ""}}
            """, for: request)
        }
        let binaryResponse = try await binaryClient.gitDiff(sessionID: "abc123", path: "logo.png")
        let binary = try XCTUnwrap(binaryResponse.diff)
        XCTAssertEqual(binary.binary, true)
        XCTAssertEqual(binary.diff, "")

        let largeClient = makeClient { request in
            apiTestJSONResponse("""
            {"diff": {"path": "huge.txt", "kind": "unstaged", "binary": false, "too_large": true,
              "additions": 0, "deletions": 0, "diff": ""}}
            """, for: request)
        }
        let largeResponse = try await largeClient.gitDiff(sessionID: "abc123", path: "huge.txt")
        let large = try XCTUnwrap(largeResponse.diff)
        XCTAssertEqual(large.tooLarge, true)
    }

    func testGitDiffNonRepositorySurfacesHTTPError() async throws {
        let client = makeClient { request in
            self.errorResponse(#"{"error": "Not a git repository", "code": "git_failed"}"#, status: 400, for: request)
        }

        do {
            _ = try await client.gitDiff(sessionID: "abc123", path: "a.txt")
            XCTFail("Expected an HTTP error for a non-repo diff.")
        } catch let APIError.http(statusCode, _) {
            XCTAssertEqual(statusCode, 400)
        }
    }

    // MARK: - git writes

    func testRemoteActionsBuildExpectedRequestsAndDecodeStatus() async throws {
        let expectedPaths = ["/api/git/fetch", "/api/git/pull", "/api/git/push"]
        var receivedPaths: [String] = []
        let client = makeClient { request in
            receivedPaths.append(request.url?.path ?? "")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(try self.jsonBody(request)["session_id"] as? String, "abc123")
            return apiTestJSONResponse(#"{"ok":true,"message":"done","status":{"is_git":true,"branch":"main"}}"#, for: request)
        }

        let responses = try await [
            client.gitFetch(sessionID: "abc123"),
            client.gitPull(sessionID: "abc123"),
            client.gitPush(sessionID: "abc123")
        ]

        XCTAssertEqual(receivedPaths, expectedPaths)
        XCTAssertTrue(responses.allSatisfy { $0.ok == true && $0.status?.branch == "main" })
    }

    func testCheckoutAndStashCheckoutBuildExpectedBodies() async throws {
        var requestIndex = 0
        let client = makeClient { request in
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["session_id"] as? String, "abc123")
            XCTAssertEqual(body["ref"] as? String, "origin/feature")
            XCTAssertEqual(body["mode"] as? String, "remote")
            XCTAssertEqual(body["new_branch"] as? String, "feature")
            XCTAssertEqual(body["track"] as? Bool, true)
            if requestIndex == 0 {
                XCTAssertEqual(request.url?.path, "/api/git/checkout")
                XCTAssertEqual(body["dirty_mode"] as? String, "block")
            } else {
                XCTAssertEqual(request.url?.path, "/api/git/stash-checkout")
                XCTAssertNil(body["dirty_mode"])
            }
            requestIndex += 1
            return apiTestJSONResponse(#"{"ok":true,"current_branch":"feature","status":{"branch":"feature"},"branches":{"current":"feature"}}"#, for: request)
        }
        let target = GitCheckoutTarget(ref: "origin/feature", mode: .remote, newBranch: "feature", track: true)

        let checkout = try await client.gitCheckout(sessionID: "abc123", target: target)
        let stashCheckout = try await client.gitStashCheckout(sessionID: "abc123", target: target)

        XCTAssertEqual(checkout.currentBranch, "feature")
        XCTAssertEqual(checkout.resolvedStatus?.branch, "feature")
        XCTAssertEqual(stashCheckout.branches?.current, "feature")
    }

    func testCreateBranchSendsNewModeNotLocal() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/checkout")
            let body = try self.jsonBody(request)
            // "local" would just switch to ref and ignore new_branch; creating a branch
            // must use the server's "new" mode (issue #315 follow-up).
            XCTAssertEqual(body["mode"] as? String, "new")
            XCTAssertEqual(body["ref"] as? String, "main")
            XCTAssertEqual(body["new_branch"] as? String, "hermex/test2")
            return apiTestJSONResponse(#"{"ok":true,"current_branch":"hermex/test2","status":{"is_git":true,"branch":"hermex/test2"},"branches":{"is_git":true,"current":"hermex/test2"}}"#, for: request)
        }

        let target = GitCheckoutTarget(ref: "main", mode: .local, newBranch: "hermex/test2")
        let response = try await client.gitCheckout(sessionID: "abc123", target: target)
        XCTAssertEqual(response.currentBranch, "hermex/test2")
    }

    func testGitErrorEnvelopeExposesStructuredCodeAndMessage() async throws {
        let client = makeClient { request in
            self.errorResponse(
                #"{"error":"A session run is active","code":"active_stream"}"#,
                status: 409,
                for: request
            )
        }

        do {
            _ = try await client.gitPull(sessionID: "abc123")
            XCTFail("Expected the active-stream error.")
        } catch let error as APIError {
            XCTAssertEqual(error.serverCode, "active_stream")
            XCTAssertEqual(error.serverMessage, "A session run is active")
        }
    }

    // MARK: - Commit flow (issue #315, Slice C)

    func testStageAndUnstageBuildBodiesAndDecodeStatusUnderGitKey() async throws {
        var receivedPaths: [String] = []
        let client = makeClient { request in
            receivedPaths.append(request.url?.path ?? "")
            XCTAssertEqual(request.httpMethod, "POST")
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["session_id"] as? String, "abc123")
            XCTAssertEqual(body["paths"] as? [String], ["Sources/App.swift", "README.md"])
            return apiTestJSONResponse(#"{"ok":true,"git":{"is_git":true,"branch":"main","totals":{"staged":2}}}"#, for: request)
        }

        let stage = try await client.gitStage(sessionID: "abc123", paths: ["Sources/App.swift", "README.md"])
        let unstage = try await client.gitUnstage(sessionID: "abc123", paths: ["Sources/App.swift", "README.md"])

        XCTAssertEqual(receivedPaths, ["/api/git/stage", "/api/git/unstage"])
        XCTAssertEqual(stage.ok, true)
        XCTAssertEqual(stage.resolvedStatus?.branch, "main")
        XCTAssertEqual(stage.resolvedStatus?.totals?.staged, 2)
        XCTAssertEqual(unstage.resolvedStatus?.branch, "main")
    }

    func testDiscardBuildsBodyWithDeleteUntrackedFlag() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/discard")
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["paths"] as? [String], ["junk.tmp"])
            XCTAssertEqual(body["delete_untracked"] as? Bool, true)
            return apiTestJSONResponse(#"{"ok":true,"git":{"is_git":true,"branch":"main"}}"#, for: request)
        }

        let response = try await client.gitDiscard(sessionID: "abc123", paths: ["junk.tmp"], deleteUntracked: true)
        XCTAssertEqual(response.resolvedStatus?.branch, "main")
    }

    func testCommitBuildsBodyAndDecodesShaAndStatusUnderStatusKey() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/commit")
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["session_id"] as? String, "abc123")
            XCTAssertEqual(body["message"] as? String, "Fix the thing")
            return apiTestJSONResponse(#"{"ok":true,"commit":"a1b2c3d","status":{"is_git":true,"branch":"main","totals":{"changed":0}}}"#, for: request)
        }

        let response = try await client.gitCommit(sessionID: "abc123", message: "Fix the thing")
        XCTAssertEqual(response.ok, true)
        XCTAssertEqual(response.shortSHA, "a1b2c3d")
        XCTAssertEqual(response.resolvedStatus?.changedCount, 0)
    }

    func testCommitSelectedBuildsBodyWithPathsAndDecodes() async throws {
        let client = makeClient { request in
            XCTAssertEqual(request.url?.path, "/api/git/commit-selected")
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["message"] as? String, "Partial commit")
            XCTAssertEqual(body["paths"] as? [String], ["a.swift"])
            return apiTestJSONResponse(#"{"ok":true,"commit":"deadbee","paths":["a.swift"],"status":{"is_git":true,"branch":"main"}}"#, for: request)
        }

        let response = try await client.gitCommitSelected(sessionID: "abc123", message: "Partial commit", paths: ["a.swift"])
        XCTAssertEqual(response.shortSHA, "deadbee")
        XCTAssertEqual(response.paths, ["a.swift"])
        XCTAssertEqual(response.resolvedStatus?.branch, "main")
    }

    func testCommitMessageEndpointsBuildBodiesAndDecodeTruncation() async throws {
        var receivedPaths: [String] = []
        let client = makeClient { request in
            receivedPaths.append(request.url?.path ?? "")
            let body = try self.jsonBody(request)
            XCTAssertEqual(body["session_id"] as? String, "abc123")
            if request.url?.path == "/api/git/commit-message-selected" {
                XCTAssertEqual(body["paths"] as? [String], ["a.swift"])
                return apiTestJSONResponse(#"{"ok":true,"message":"selected msg","truncated":true}"#, for: request)
            }
            XCTAssertNil(body["paths"])
            return apiTestJSONResponse(#"{"ok":true,"message":"all msg","truncated":false}"#, for: request)
        }

        let all = try await client.gitCommitMessage(sessionID: "abc123")
        let selected = try await client.gitCommitMessageSelected(sessionID: "abc123", paths: ["a.swift"])

        XCTAssertEqual(receivedPaths, ["/api/git/commit-message", "/api/git/commit-message-selected"])
        XCTAssertEqual(all.message, "all msg")
        XCTAssertEqual(all.truncated, false)
        XCTAssertEqual(selected.message, "selected msg")
        XCTAssertEqual(selected.truncated, true)
    }

    func testCommitDestructiveDisabledSurfacesStructuredCode() async throws {
        let client = makeClient { request in
            self.errorResponse(
                #"{"error":"Destructive git writes are disabled","code":"destructive_git_disabled"}"#,
                status: 403,
                for: request
            )
        }

        do {
            _ = try await client.gitCommit(sessionID: "abc123", message: "msg")
            XCTFail("Expected the destructive-disabled error.")
        } catch let error as APIError {
            XCTAssertEqual(error.serverCode, "destructive_git_disabled")
        }
    }

    func testCommitMessageRequestsUseExtendedTimeout() async throws {
        let client = makeClient { request in
            XCTAssertGreaterThanOrEqual(request.timeoutInterval, 120, "LLM message generation needs a wide timeout, not the 60s default.")
            return apiTestJSONResponse(#"{"ok":true,"message":"m","truncated":false}"#, for: request)
        }

        _ = try await client.gitCommitMessage(sessionID: "abc123")
        _ = try await client.gitCommitMessageSelected(sessionID: "abc123", paths: ["a.swift"])
    }

    func testCommitEmptyMessageSurfacesBadRequest() async throws {
        let client = makeClient { request in
            self.errorResponse(#"{"error":"Commit message is required"}"#, status: 400, for: request)
        }

        do {
            _ = try await client.gitCommit(sessionID: "abc123", message: "")
            XCTFail("Expected the empty-message rejection.")
        } catch let error as APIError {
            XCTAssertEqual(error.serverMessage, "Commit message is required")
        }
    }
}
