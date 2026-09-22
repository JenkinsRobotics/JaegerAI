import Foundation

struct SlashCommand: Identifiable, Equatable {
    let id = UUID()
    let name: String
    let description: String
    let argHint: String?
    let noEcho: Bool
    let handler: SlashCommandHandler
    let subArgs: SlashCommandSubArgs

    init(
        name: String,
        description: String,
        argHint: String? = nil,
        noEcho: Bool = false,
        handler: SlashCommandHandler = .unsupported,
        subArgs: SlashCommandSubArgs = .none
    ) {
        self.name = name
        self.description = description
        self.argHint = argHint
        self.noEcho = noEcho
        self.handler = handler
        self.subArgs = subArgs
    }

    static func == (lhs: SlashCommand, rhs: SlashCommand) -> Bool {
        lhs.name == rhs.name
    }
}

enum SlashCommandHandler: Equatable {
    case unsupported
    case clientSide(ClientSideAction)
    case serverSide(ServerSideAction)
}

enum ClientSideAction: String, Equatable {
    case clear
    case stop
    case new
    case help
}

enum ServerSideAction: String, Equatable {
    case model
    case workspace
    case reasoning
    case title
    case personality
    case skills
    case compress
    case retry
    case undo
    case branch
    case queue
    case steer
    case interrupt
    case status
    case btw
    case background
    case goal
}

enum SlashCommandSubArgs: Equatable {
    case none
    case models
    case personalities
    case reasoningLevels
    case workspaces
    case skills
    case goalActions
}
