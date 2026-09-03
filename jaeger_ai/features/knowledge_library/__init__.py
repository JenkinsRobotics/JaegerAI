"""Folder-backed notes, library, and document-ingestion feature."""

from .store import KnowledgeLibrary, LibraryError

__all__ = ["KnowledgeLibrary", "LibraryError"]
