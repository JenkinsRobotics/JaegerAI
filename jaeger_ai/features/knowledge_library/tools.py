"""Agent-facing knowledge library tools."""

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .store import KnowledgeLibrary, LibraryError


def _library() -> KnowledgeLibrary:
    from jaeger_ai.main import _pipeline

    layout = _pipeline.get("layout")
    if layout is None:
        raise RuntimeError("Jaeger instance is not bound")
    return KnowledgeLibrary(layout.memory_dir / "library.db")


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="knowledge_library",
    operation="library_add",
    summary="register a local directory for document indexing",
)
def library_add(path: str, label: str = "") -> dict:
    """Register a local notes or document folder as a read-only knowledge collection."""
    library = _library()
    try:
        return {"ok": True, "collection": library.add(path, label)}
    except (LibraryError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
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
