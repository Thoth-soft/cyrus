# Contributing to Sekha

## Development Setup

1. Clone the repository:
   ```
   git clone https://github.com/Thoth-soft/sekha.git
   cd sekha
   ```

2. Create a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   ```

3. Install in development mode:
   ```
   pip install -e .
   ```

4. Run tests:
   ```
   python -m unittest discover -s tests -v
   ```

## Running Tests

```
python -m unittest discover -s tests -v
```

Tests must pass on Windows, macOS, and Linux with Python 3.11, 3.12, and 3.13.

## Pull Requests

- All PRs must pass CI on all matrix cells before merge
- Zero runtime dependencies -- do not add entries to `[project.dependencies]`
- Use `pathlib.Path` for all filesystem operations -- `os.path` is banned
- All logging goes to stderr -- stdout is reserved for protocol messages

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
