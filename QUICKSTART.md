# Quick Start Guide

Get up and running in less than 2 minutes!

## One-Command Setup (Fastest)

```bash
./setup.sh
```

This script will:

- ✓ Check Python version
- ✓ Offer to install uv (10-100x faster than pip)
- ✓ Create virtual environment
- ✓ Install all dependencies
- ✓ Set up pre-commit hooks
- ✓ Create .env file

## Manual Setup (3 Steps)

### 1. Install uv (Recommended)

**Linux/macOS:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Install Dependencies

```bash
# Create and activate virtual environment
uv venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies (10-100x faster with uv!)
uv pip install -e ".[dev]"
```

### 3. Set Up Pre-commit

```bash
pre-commit install
```

## Using Make (Convenience Commands)

```bash
# Set up everything automatically
make dev

# Run the application
make run

# Run tests
make test

# Format and lint code
make format
make lint

# See all commands
make help
```

## Next Steps

1. **Configure environment:**

   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

2. **Run migrations:**

   ```bash
   make migrate
   # or: alembic upgrade head
   ```

3. **Start the server:**

   ```bash
   make run
   # or: uvicorn src.main:app --reload
   ```

4. **Visit the API:**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

## Why uv?

uv is a drop-in replacement for pip that's **10-100x faster**:

- ⚡ **Blazing Fast**: Written in Rust, parallel downloads
- 🔒 **Reliable**: Deterministic resolution, proper lockfiles
- 🎯 **Compatible**: Works with existing requirements.txt and pyproject.toml
- 📦 **Modern**: Supports PEP 660, 621, 631, and more

### Speed Comparison

Installing this project's dependencies:

| Tool | Time |
| ---- | ---- |
| pip  | ~30s |
| uv   | ~3s  |

**10x faster installations = 10x more productivity!**

## Troubleshooting

**Q: Python 3.11 not found?**

```bash
# Install Python 3.11+ first
# Ubuntu/Debian:
sudo apt update && sudo apt install python3.11

# macOS (Homebrew):
brew install python@3.11

# Or use pyenv:
pyenv install 3.11.7
pyenv local 3.11.7
```

**Q: uv command not found after installation?**

```bash
# Reload your shell configuration
source ~/.bashrc  # or ~/.zshrc
# or restart your terminal
```

**Q: Permission denied when running setup.sh?**

```bash
chmod +x setup.sh
./setup.sh
```

## More Information

- Full documentation: [README.md](README.md)
- Coding standards: [context/coding-standards.md](context/coding-standards.md)
- uv documentation: https://github.com/astral-sh/uv
