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
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    if [ "$PYTHON_MAJOR" -gt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; }; then
        PYTHON_CMD=python3
    else
        echo -e "${RED}Error: Python 3.11+ is required (found ${PYTHON_MAJOR}.${PYTHON_MINOR})${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: Python 3.11+ not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $(${PYTHON_CMD} --version | cut -d' ' -f2) found${NC}"
echo ""

# Check if uv is installed
echo -e "${YELLOW}Checking for uv...${NC}"
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${YELLOW}uv not found. Would you like to install it? (recommended for 10-100x faster installation)${NC}"
    echo -e "${YELLOW}Installation command: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    read -p "Install uv? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Installing uv...${NC}"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Ensure common uv install locations are in PATH for this session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        if command -v uv >/dev/null 2>&1; then
            echo -e "${GREEN}✓ uv installed successfully${NC}"
            USE_UV=true
        else
            echo -e "${YELLOW}⚠ uv installation may require shell restart. Using pip for now.${NC}"
            USE_UV=false
        fi
    else
        echo -e "${YELLOW}Skipping uv installation. Using pip.${NC}"
        USE_UV=false
    fi
else
    echo -e "${GREEN}✓ uv $(uv --version) found${NC}"
    USE_UV=true
fi
echo ""

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [ -d ".venv" ]; then
    echo -e "${YELLOW}Virtual environment already exists. Skipping creation.${NC}"
else
    if [ "$USE_UV" = true ]; then
        uv venv --python ${PYTHON_CMD}
    else
        ${PYTHON_CMD} -m venv .venv
    fi
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"
echo ""

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
if [ "$USE_UV" = true ]; then
    echo -e "${BLUE}Using uv (fast mode)...${NC}"
    uv pip install -e ".[dev]"
else
    echo -e "${BLUE}Using pip...${NC}"
    pip install -e ".[dev]"
fi
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
