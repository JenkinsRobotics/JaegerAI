"""Test fixtures — sample data for tests."""

from __future__ import annotations

from pathlib import Path

# Sample chat messages
SAMPLE_MESSAGES = [
    {"role": "user", "content": "Hello, how are you?"},
    {"role": "assistant", "content": "I'm doing well, thank you! How can I help you today?"},
    {"role": "user", "content": "What's the weather like?"},
    {"role": "assistant", "content": "I don't have access to real-time weather data, but I can help you find a weather service!"},
]

# Sample code for syntax highlighting tests
SAMPLE_CODE = {
    "python": '''
def hello_world():
    """Say hello to the world."""
    print("Hello, World!")
    return True

if __name__ == "__main__":
    hello_world()
''',
    "javascript": '''
function helloWorld() {
    console.log("Hello, World!");
    return true;
}

helloWorld();
''',
    "typescript": '''
interface Person {
    name: string;
    age: number;
}

function greet(person: Person): string {
    return `Hello, ${person.name}!`;
}
''',
    "json": '''
{
    "name": "JaegerAI",
    "version": "0.13.0",
    "features": ["chat", "voice", "vision"],
    "enabled": true
}
''',
}

# Sample markdown
SAMPLE_MARKDOWN = """# Heading 1
## Heading 2
### Heading 3

This is **bold** and *italic* text.

- List item 1
- List item 2
  - Nested item

1. Numbered item 1
2. Numbered item 2

```python
print("Hello, World!")
```

> A blockquote

[Link to JaegerAI](https://github.com/JenkinsRobotics/JaegerAI)

| Table | Header |
|-------|--------|
| Cell 1 | Cell 2 |
"""

# Sample file upload data
SAMPLE_FILES = {
    "text": ("test.txt", "Hello, this is a test file.", "text/plain"),
    "json": ("data.json", '{"key": "value"}', "application/json"),
    "image": ("test.png", b"\x89PNG\r\n\x1a\n...", "image/png"),
}

# Sample sessions
SAMPLE_SESSIONS = [
    {"id": "sess-001", "title": "Project Discussion", "message_count": 25},
    {"id": "sess-002", "title": "Code Review", "message_count": 42},
    {"id": "sess-003", "title": "Bug Fix", "message_count": 8},
]

# Sample agents
SAMPLE_AGENTS = [
    {"id": "agent-001", "name": "Assistant", "personality": "assistant"},
    {"id": "agent-002", "name": "Jarvis", "personality": "jarvis"},
    {"id": "agent-003", "name": "Lilith", "personality": "lilith"},
]


def get_fixture_path(name: str) -> Path:
    """Get path to a fixture file."""
    return Path(__file__).parent.parent / "fixtures" / name
