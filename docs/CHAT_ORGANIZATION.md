# Chat organization

Open **Manage** above the sidebar, or a conversation's ellipsis.
Search and select chats to rename, pin, reorder, move, archive or restore.
**Archived** shows saved conversations that are hidden from normal navigation.
Permanent deletion remains behind its own confirmation.

Create named projects and sections in the manager. A project groups chats and
can hold shared reference notes for future turns. A section controls placement
in the sidebar. Group membership never changes a chat's execution workspace,
model, tool permissions or code-project grants. Removing a group keeps its chats.

**AI name** explicitly requests descriptive new titles for selected chats.
**Preview AI suggestions** uses the configured provider with no tools and a
bounded excerpt of up to 40 selected chats. It preserves manual titles by default.
Review the proposal before applying it; **Undo last change** reverses organization
without removing messages. Conflicting edits cause a refresh error, never a
silent overwrite. The agent's session_organize tool can read organization and
save proposals; it cannot apply changes or delete chats.

Gateway's session SQLite database owns groups, memberships, names, pins and
operation history. The Mac and browser clients refresh organization every five
seconds and on focus. Existing local pins migrate once. Existing filesystem
workspace groupings remain visible until explicitly assigned or ungrouped.
