import Foundation

extension MarkdownMathFormatter {
    static func replacingAligned(in value: String) -> String {
        let begin = #"\begin{aligned}"#
        let end = #"\end{aligned}"#
        var result = value

        while let beginRange = result.range(of: begin),
              let endRange = result.range(of: end, range: beginRange.upperBound..<result.endIndex) {
            let body = String(result[beginRange.upperBound..<endRange.lowerBound])
            result.replaceSubrange(beginRange.lowerBound..<endRange.upperBound, with: renderedAligned(body))
        }

        return result
    }

    static func replacingCases(in value: String) -> String {
        let begin = #"\begin{cases}"#
        let end = #"\end{cases}"#
        var result = value

        while let beginRange = result.range(of: begin),
              let endRange = result.range(of: end, range: beginRange.upperBound..<result.endIndex) {
            let body = String(result[beginRange.upperBound..<endRange.lowerBound])
            result.replaceSubrange(beginRange.lowerBound..<endRange.upperBound, with: renderedCases(body))
        }

        return result
    }

    static func replacingMatrices(in value: String) -> String {
        var result = value

        for environment in MatrixEnvironment.allCases {
            while let beginRange = result.range(of: environment.beginToken),
                  let endRange = result.range(of: environment.endToken, range: beginRange.upperBound..<result.endIndex) {
                let body = String(result[beginRange.upperBound..<endRange.lowerBound])
                result.replaceSubrange(beginRange.lowerBound..<endRange.upperBound, with: renderedMatrix(body, environment: environment))
            }
        }

        return result
    }

    private static func renderedAligned(_ body: String) -> String {
        body
            .components(separatedBy: #"\\"#)
            .map { row in
                renderedText(for: row.replacingOccurrences(of: "&", with: ""))
            }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
    }

    private static func renderedCases(_ body: String) -> String {
        let rows = body
            .components(separatedBy: #"\\"#)
            .map { row in
                renderedText(for: row.replacingOccurrences(of: "&", with: ""))
            }
            .filter { !$0.isEmpty }

        guard !rows.isEmpty else { return "" }
        if rows.count == 1 {
            return "{ \(rows[0])"
        }

        return rows.enumerated().map { index, row in
            let bracket: String
            if index == 0 {
                bracket = "⎧"
            } else if index == rows.count - 1 {
                bracket = "⎩"
            } else {
                bracket = "⎨"
            }
            return "\(bracket) \(row)"
        }
        .joined(separator: "\n")
    }

    private static func renderedMatrix(_ body: String, environment: MatrixEnvironment) -> String {
        let rows = body
            .components(separatedBy: #"\\"#)
            .map { row in
                row
                    .components(separatedBy: "&")
                    .map { renderedText(for: $0).trimmingCharacters(in: .whitespacesAndNewlines) }
            }
            .filter { !$0.isEmpty }

        guard !rows.isEmpty else { return "" }

        let columnCount = rows.map(\.count).max() ?? 0
        let widths = (0..<columnCount).map { column in
            rows.map { row in row.indices.contains(column) ? row[column].count : 0 }.max() ?? 0
        }

        return rows.enumerated().map { rowIndex, row in
            let brackets = environment.brackets(rowIndex: rowIndex, rowCount: rows.count)
            let cells = (0..<columnCount).map { column -> String in
                let value = row.indices.contains(column) ? row[column] : ""
                return value.padding(toLength: widths[column], withPad: " ", startingAt: 0)
            }
            return "\(brackets.left) \(cells.joined(separator: "  ")) \(brackets.right)"
        }
        .joined(separator: "\n")
    }
}

private enum MatrixEnvironment: CaseIterable {
    case parentheses
    case brackets

    var beginToken: String {
        switch self {
        case .parentheses:
            return #"\begin{pmatrix}"#
        case .brackets:
            return #"\begin{bmatrix}"#
        }
    }

    var endToken: String {
        switch self {
        case .parentheses:
            return #"\end{pmatrix}"#
        case .brackets:
            return #"\end{bmatrix}"#
        }
    }

    func brackets(rowIndex: Int, rowCount: Int) -> (left: String, right: String) {
        if rowCount == 1 {
            switch self {
            case .parentheses:
                return ("(", ")")
            case .brackets:
                return ("[", "]")
            }
        }

        switch (self, rowIndex, rowCount - 1) {
        case (.parentheses, 0, _):
            return ("⎛", "⎞")
        case (.parentheses, let row, let last) where row == last:
            return ("⎝", "⎠")
        case (.parentheses, _, _):
            return ("⎜", "⎟")
        case (.brackets, 0, _):
            return ("⎡", "⎤")
        case (.brackets, let row, let last) where row == last:
            return ("⎣", "⎦")
        case (.brackets, _, _):
            return ("⎢", "⎥")
        }
    }
}
