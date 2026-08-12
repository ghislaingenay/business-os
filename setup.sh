#!/usr/bin/env bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Business OS - Development Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_CMD=python3.11
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    if [ "$(echo "$PYTHON_VERSION >= 3.11" | bc -l)" -eq 1 ]; then
        PYTHON_CMD=python3
    else
        echo -e "${RED}Error: Python 3.11+ is required (found $PYTHON_VERSION)${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: Python 3.11+ not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $(${PYTHON_CMD} --version | cut -d' ' -f2) found${NC}"
echo ""

# Check if uv is installed, if not install it automatically (REQUIRED)
echo -e "${YELLOW}Checking for uv...${NC}"
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${YELLOW}uv not found. Installing uv (required for this project)...${NC}"
    echo -e "${BLUE}Running: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    echo ""

    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # Reload shell config to get uv in PATH
        export PATH="$HOME/.cargo/bin:$PATH"

        if command -v uv >/dev/null 2>&1; then
            echo -e "${GREEN}✓ uv $(uv --version) installed successfully${NC}"
        else
            echo -e "${RED}Error: uv installation completed but uv command not found in PATH${NC}"
            echo -e "${RED}Please restart your shell and run this script again, or manually add uv to PATH:${NC}"
            echo -e "${YELLOW}  export PATH=\"\$HOME/.cargo/bin:\$PATH\"${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Error: Failed to install uv${NC}"
        echo -e "${RED}Please install uv manually:${NC}"
        echo -e "${YELLOW}  curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
        echo -e "${YELLOW}Or visit: https://github.com/astral-sh/uv${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ uv $(uv --version) found${NC}"
fi
echo ""

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [ -d ".venv" ]; then
    echo -e "${YELLOW}Virtual environment already exists. Skipping creation.${NC}"
else
    uv venv --python ${PYTHON_CMD}
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"
echo ""

# Install dependencies
echo -e "${YELLOW}Installing dependencies with uv...${NC}"
uv pip install -e ".[dev]"
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Install pre-commit hooks
echo -e "${YELLOW}Installing pre-commit hooks...${NC}"
pre-commit install
echo -e "${GREEN}✓ Pre-commit hooks installed${NC}"
echo ""

# Set up environment file
echo -e "${YELLOW}Setting up environment file...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ Created .env from .env.example${NC}"
        echo -e "${YELLOW}⚠ Please edit .env with your configuration${NC}"
    else
        echo -e "${YELLOW}⚠ No .env.example found. You may need to create .env manually${NC}"
    fi
else
    echo -e "${GREEN}✓ .env already exists${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. Edit .env with your configuration"
echo -e "  2. Run database migrations: ${YELLOW}make migrate${NC}"
echo -e "  3. Start the application: ${YELLOW}make run${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo -e "  ${YELLOW}make help${NC}        - Show all available commands"
echo -e "  ${YELLOW}make test${NC}        - Run tests"
echo -e "  ${YELLOW}make lint${NC}        - Check code quality"
echo -e "  ${YELLOW}make format${NC}      - Format code"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo -e "  See README.md for complete documentation"
echo -e "  See context/coding-standards.md for coding guidelines"
echo ""
