"""Agent-facing knowledge library tools."""

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .store import KnowledgeLibrary, LibraryError


def _library() -> KnowledgeLibrary:
    # Gateway and CLI both bind this canonical workspace owner. Importing
    # main._pipeline here created a second, usually uninitialized binding in
    # the daemon and made the real Library UI fail despite mocked route tests.
    from jaeger_agent.core.workspace import get_layout

    layout = get_layout()
    return KnowledgeLibrary(layout.memory_dir / "library.db")


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_add",
    summary="register a local directory for document indexing",
)
def library_add(path: str, label: str = "") -> dict:
    """Idempotently register a folder and always return its collection ID."""
    library = _library()
    try:
        return {"ok": True, "collection": library.add(path, label)}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()


@register_tool_from_function(side_effect="read")
def library_collections() -> dict:
    """List registered knowledge collections with IDs, roots, and index status."""
    library = _library()
    try:
        return {"ok": True, "collections": library.list()}
    finally:
        library.close()


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_index",
    summary="write a searchable index of local documents",
)
def library_index(collection_id: str) -> dict:
    """Incrementally index safe text documents in a registered collection."""
    library = _library()
    try:
        return {"ok": True, **library.index(collection_id)}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_sync_reminders",
    summary="synchronize Apple Reminders into the searchable knowledge library",
)
def library_sync_reminders(include_completed: bool = True) -> dict:
    """Read Apple Reminders through EventKit and durably index the snapshot."""
    from jaeger_agent.tools import native_pim

    snapshot = native_pim.run("reminders", include_completed=include_completed)
    if not snapshot or not snapshot.get("ok"):
        return {"ok": False, "error": str((snapshot or {}).get("error") or
                                            "Jaeger PIM helper is unavailable")}
    documents = []
    for reminder in snapshot.get("reminders") or []:
        external_id = str(reminder.get("id") or "").strip()
        if not external_id:
            # Compatibility with an older helper while it is being rebuilt.
            import hashlib
            identity = "\0".join(str(reminder.get(key) or "")
                                  for key in ("list", "title", "due"))
            external_id = hashlib.sha256(identity.encode()).hexdigest()
        details = [f"List: {reminder.get('list') or ''}",
                   f"Completed: {bool(reminder.get('completed'))}"]
        if reminder.get("due"):
            details.append(f"Due: {reminder['due']}")
        if reminder.get("notes"):
            details.extend(("", str(reminder["notes"])))
        documents.append({
            "external_id": external_id,
            "title": str(reminder.get("title") or "Untitled reminder"),
            "content": "\n".join(details),
            "provenance": {"source": "EventKit", "list": reminder.get("list") or ""},
        })
    library = _library()
    try:
        return {"ok": True, **library.sync_source(
            "apple-reminders", "Apple Reminders", documents, full_snapshot=True
        )}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_sync_mail",
    summary="synchronize an Apple Mail mailbox into the searchable knowledge library",
)
def library_sync_mail(account: str, mailbox: str = "INBOX", max_messages: int = 500,
                      start_offset: int = 0) -> dict:
    """Page through Apple Mail safely and index headers plus bounded body text."""
    from jaeger_agent.tools import email

    maximum = max(1, min(int(max_messages), 5_000))
    initial_offset = max(0, int(start_offset))
    offset = initial_offset
    headers: list[dict] = []
    complete = False
    while len(headers) < maximum:
        page = email.list_mail(account, mailbox, limit=min(25, maximum - len(headers)),
                               unread_only=False, offset=offset)
        if not page.get("ok"):
            return {"ok": False, "error": str(page.get("error") or "Mail read failed"),
                    "offset": offset}
        batch = list(page.get("messages") or [])
        headers.extend(batch)
        next_offset = page.get("next_offset")
        if next_offset is None or not batch:
            complete = True
            break
        offset = int(next_offset)

    bodies: dict[str, dict] = {}
    for start in range(0, len(headers), 5):
        ids = [str(row.get("id") or "") for row in headers[start:start + 5]]
        page = email.read_mail(account, mailbox, ids)
        if not page.get("ok"):
            return {"ok": False, "error": str(page.get("error") or "Mail body read failed"),
                    "indexed_headers": start}
        bodies.update({str(row.get("id")): row for row in page.get("messages") or []})

    documents = []
    for header in headers:
        message_id = str(header.get("id") or "").strip()
        body = bodies.get(message_id, {})
        content = "\n".join((
            f"From: {header.get('sender') or body.get('sender') or ''}",
            f"Date: {header.get('date') or body.get('date') or ''}",
            f"Mailbox: {mailbox}", "", str(body.get("snippet") or ""),
        ))
        documents.append({
            "external_id": message_id,
            "title": str(header.get("subject") or body.get("subject") or "(no subject)"),
            "content": content,
            "provenance": {"source": "Apple Mail", "account": account, "mailbox": mailbox},
        })
    library = _library()
    try:
        source_id = f"apple-mail:{account}:{mailbox}"
        return {"ok": True, **library.sync_source(
            source_id, f"Apple Mail — {account}/{mailbox}", documents,
            full_snapshot=complete and initial_offset == 0,
        ), "next_offset": None if complete else offset, "truncated": not complete}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_sync_apple_notes",
    summary="synchronize Apple Notes into the searchable knowledge library",
)
def library_sync_apple_notes(max_notes: int = 300, start_index: int = 1,
                             refresh: bool = True) -> dict:
    """Index Apple Notes through the installed memo CLI without modifying Notes."""
    import hashlib
    import re
    import shutil
    import subprocess

    memo = shutil.which("memo")
    if not memo:
        return {"ok": False, "error": "memo CLI is not installed"}
    first = max(1, int(start_index))
    maximum = max(1, min(int(max_notes), 2_000))
    command = [memo, "notes"] + (["--no-cache"] if refresh and first == 1 else [])
    try:
        listing = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"Apple Notes listing failed: {exc}"}
    if listing.returncode:
        return {"ok": False, "error": (listing.stderr or listing.stdout).strip()}
    rows = [(int(match.group(1)), match.group(2).strip())
            for line in listing.stdout.splitlines()
            if (match := re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", line))]
    selected = [(number, title) for number, title in rows if number >= first][:maximum]
    documents = []
    for number, title in selected:
        try:
            viewed = subprocess.run([memo, "notes", "--view", str(number)],
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": f"Apple Note {number} read failed: {exc}",
                    "indexed_notes": len(documents)}
        if viewed.returncode:
            return {"ok": False, "error": (viewed.stderr or viewed.stdout).strip(),
                    "indexed_notes": len(documents)}
        body = viewed.stdout.strip()
        external_id = hashlib.sha256(title.encode()).hexdigest()
        documents.append({"external_id": external_id, "title": title, "content": body,
                          "provenance": {"source": "Apple Notes via memo",
                                         "list_index": number}})
    remaining = [number for number, _ in rows if number > (selected[-1][0] if selected else first - 1)]
    complete = not remaining
    library = _library()
    try:
        receipt = library.sync_source(
            "apple-notes", "Apple Notes", documents,
            full_snapshot=complete and first == 1,
        )
        return {"ok": True, **receipt, "truncated": not complete,
                "next_index": remaining[0] if remaining else None,
                "available_notes": len(rows)}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()


@register_tool_from_function(side_effect="read")
def library_search(query: str, limit: int = 20) -> dict:
    """Full-text search all indexed notes and documents."""
    library = _library()
    try:
        return {"ok": True, "results": library.search(query, limit)}
    finally:
        library.close()


@register_tool_from_function(side_effect="read")
def library_read(document_id: str) -> dict:
    """Read one indexed document by the opaque id returned from library_search."""
    library = _library()
    try:
        return {"ok": True, "document": library.read(document_id)}
    except LibraryError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        library.close()
