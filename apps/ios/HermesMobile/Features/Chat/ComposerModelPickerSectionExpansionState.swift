import Foundation

struct ComposerModelPickerSectionExpansionState {
    private var expandedGroupIDs: Set<String> = []
    private var collapsedSearchGroupIDs: Set<String> = []
    private var searchQuery = ""

    mutating func updateSearchText(_ searchText: String) {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query != searchQuery else { return }

        searchQuery = query
        collapsedSearchGroupIDs.removeAll()
    }

    func isExpanded(groupID: String) -> Bool {
        if searchQuery.isEmpty {
            return expandedGroupIDs.contains(groupID)
        }

        return !collapsedSearchGroupIDs.contains(groupID)
    }

    mutating func setExpanded(_ isExpanded: Bool, groupID: String) {
        if searchQuery.isEmpty {
            if isExpanded {
                expandedGroupIDs.insert(groupID)
            } else {
                expandedGroupIDs.remove(groupID)
            }
        } else if isExpanded {
            collapsedSearchGroupIDs.remove(groupID)
        } else {
            collapsedSearchGroupIDs.insert(groupID)
        }
    }
}
