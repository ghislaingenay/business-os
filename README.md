# Business OS

FastAPI backend with strict domain-driven design, using Python 3.11+, Pydantic v2, SQLAlchemy 2.0, and dependency injection.

> 🚀 **Quick Start**: New to the project? Check out [QUICKSTART.md](QUICKSTART.md) for the fastest setup path!

## Prerequisites

- Python 3.11+
- PostgreSQL (for production) or SQLite (for development)
- Git

## Setup

### 1. Install uv (Recommended)

[uv](https://github.com/astral-sh/uv) is an extremely fast Python package installer and resolver, written in Rust.

**Linux/macOS:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Using pip:**

```bash
pip install uv
```

**Using Homebrew (macOS):**

```bash
brew install uv
```

After installation, verify:

```bash
uv --version
```

### 2. Clone the Repository

```bash
git clone <repository-url>
cd business-os
```

### 3. Create Virtual Environment and Install Dependencies

**Using uv (recommended - 10-100x faster):**

```bash
# Create virtual environment with Python 3.11+
uv venv --python 3.11

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows

# Install dependencies
uv pip install -e ".[dev]"
```

**Using standard pip:**

```bash
# Create virtual environment
python3.11 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -e ".[dev]"
```

### 4. Set Up Pre-commit Hooks

```bash
pre-commit install
```

This installs git hooks that will automatically run:

- Code formatting (Ruff)
- Linting (Ruff)
- Type checking (mypy)
- YAML/JSON validation
- Security checks

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
APP_ENVIRONMENT=development
DATABASE_URL=postgresql://user:password@localhost/business_os
# Add other configuration as needed
```

### 6. Run Database Migrations

```bash
alembic upgrade head
```

## Development

### Running the Application

```bash
uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`.

API documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Code Quality

**Run linter and formatter:**

```bash
ruff check .           # Check for issues
ruff check . --fix     # Auto-fix issues
ruff format .          # Format code
```

**Run type checker:**

```bash
mypy src/
```

**Run all pre-commit hooks manually:**

```bash
pre-commit run --all-files
```

### Testing

**Run all tests:**

```bash
pytest
```

**Run with coverage:**

```bash
pytest --cov=src --cov-report=html
```

**Run specific test:**

```bash
pytest tests/users/test_service.py
```

**Run tests matching a pattern:**

```bash
pytest -k "test_create"
```

## Project Structure

```
business-os/
├── src/                      # Application source code
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration management
│   ├── database.py          # Database setup
│   ├── container.py         # Dependency injection container
│   │
│   ├── users/               # User domain
│   │   ├── router.py        # API routes
│   │   ├── schemas.py       # Pydantic models
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── service.py       # Business logic
│   │   ├── repository.py    # Data access
│   │   └── exceptions.py    # Domain exceptions
│   │
│   └── shared/              # Shared technical components
│       ├── storage/
│       └── pagination/
│
├── tests/                   # Test suite
│   ├── users/
│   └── conftest.py
│
├── alembic/                 # Database migrations
│   └── versions/
│
├── context/                 # Project documentation & specs
│   ├── coding-standards.md
│   ├── features/
│   └── technical-designs/
│
├── .pre-commit-config.yaml  # Pre-commit hooks config
├── pyproject.toml           # Project config & dependencies
└── README.md               # This file
```

## Architecture Principles

This project follows **strict domain-driven design**:

- **Domain-centric**: Code organized by business domain, not technical layers
- **No global layers**: No global `services/`, `repositories/`, or `models/` folders
- **Thin routes**: FastAPI routes only handle HTTP concerns
- **Rich services**: Business logic lives in domain services
- **Clean boundaries**: Domain logic independent of HTTP/framework details
- **Dependency injection**: Using FastAPI `Depends` and `dependency-injector`

See [context/coding-standards.md](context/coding-standards.md) for complete coding guidelines.

## Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Follow coding standards in `context/coding-standards.md`
3. Write tests for new functionality
4. Ensure pre-commit hooks pass: `pre-commit run --all-files`
5. Run tests: `pytest`
6. Commit with conventional commits: `feat:`, `fix:`, `chore:`, etc.
7. Push and create a pull request

## Useful Commands

### Using uv (Faster)

```bash
# Sync dependencies with lockfile
uv pip sync

# Add a new dependency
uv pip install <package>

# Update all dependencies
uv pip install --upgrade -e ".[dev]"

# Compile requirements to a lockfile
uv pip compile pyproject.toml -o requirements.txt
```

### Database

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current migration
alembic current
```

### Docker (if applicable)

```bash
# Build and run
docker-compose up --build

# Run in background
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f
```

## License

[Add your license here]
