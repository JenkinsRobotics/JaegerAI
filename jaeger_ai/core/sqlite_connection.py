"""SQLite transactions whose owner releases the connection at context exit."""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        # SQLite's own context manager commits/rolls back but does not close.
        try:
            return super().__exit__(*args)
        finally:
            self.close()
