import Foundation

struct GitFileChange: Identifiable, Equatable {
    let path: String
    let indexStatus: Character
    let worktreeStatus: Character

    var id: String { path }
    var badge: String { String(worktreeStatus == " " ? indexStatus : worktreeStatus) }
}

struct WorkspaceSnapshot: Equatable {
    let repoRoot: URL
    let branch: String
    let changes: [GitFileChange]

    static func parseGitStatus(_ output: String, repoRoot: URL) -> WorkspaceSnapshot {
        var branch = "Unknown branch"
        var changes: [GitFileChange] = []

        for line in output.split(whereSeparator: \.isNewline).map(String.init) {
            if line.hasPrefix("## ") {
                branch = String(line.dropFirst(3)).components(separatedBy: "...").first ?? "Unknown branch"
                continue
            }
            guard line.count >= 4 else { continue }
            let index = line[line.startIndex]
            let worktree = line[line.index(after: line.startIndex)]
            let rawPath = String(line.dropFirst(3))
            // Porcelain v1 quotes paths containing unusual bytes. Keep the
            // quoted representation visible rather than guessing at escapes.
            let path = rawPath.components(separatedBy: " -> ").last ?? rawPath
            changes.append(GitFileChange(path: path, indexStatus: index, worktreeStatus: worktree))
        }

        return WorkspaceSnapshot(repoRoot: repoRoot, branch: branch, changes: changes)
    }

    static func load(repoRoot: URL) throws -> WorkspaceSnapshot {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        process.arguments = ["-C", repoRoot.path, "status", "--short", "--branch", "--untracked-files=all"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0,
              let output = String(data: data, encoding: .utf8) else {
            throw WorkspaceLoadError.gitFailed
        }
        return parseGitStatus(output, repoRoot: repoRoot)
    }
}

enum WorkspaceLoadError: LocalizedError {
    case gitFailed

    var errorDescription: String? {
        "Could not read Git status for this repository."
    }
}
