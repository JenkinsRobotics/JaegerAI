# core/node_state.py

"""
Global state for the Mochi node.
"""

class NodeState:
    """A simple container for the node's state."""
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.anim = None
        self.current_mode = None
        self.script = None  # Holds the active script object

# Global singleton instance of the node's state.
node_state = NodeState(64, 64)
