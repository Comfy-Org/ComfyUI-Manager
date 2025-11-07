# CLAUDE.md - Development Guidelines

## Project Context
This is ComfyUI Manager, a Python package that provides management functions for ComfyUI custom nodes, models, and extensions. The project follows modern Python packaging standards and maintains both current (`glob`) and legacy implementations.

## Code Architecture
- **Current Development**: Work in `comfyui_manager/glob/` package
- **Legacy Code**: `comfyui_manager/legacy/` (reference only, do not modify unless explicitly asked)
- **Common Utilities**: `comfyui_manager/common/` for shared functionality
- **Data Models**: `comfyui_manager/data_models/` for API schemas and types

## Development Workflow for API Changes
When modifying data being sent or received:
1. Update `openapi.yaml` file first
2. Verify YAML syntax using `yaml.safe_load`
3. Regenerate types following `data_models/README.md` instructions
4. Verify new data model generation
5. Verify syntax of generated type files
6. Run formatting and linting on generated files
7. Update `__init__.py` files in `data_models` to export new models
8. Make changes to rest of codebase
9. Run CI tests to verify changes

## Coding Standards
### Python Style
- Follow PEP 8 coding standards
- Use type hints for all function parameters and return values
- Target Python 3.9+ compatibility
- Line length: 120 characters (as configured in ruff)

### Security Guidelines
- Never hardcode API keys, tokens, or sensitive credentials
- Use environment variables for configuration
- Validate all user input and file paths
- Use prepared statements for database operations
- Implement proper error handling without exposing internal details
- Follow principle of least privilege for file/network access

### Code Quality
- Write descriptive variable and function names
- Include docstrings for public functions and classes
- Handle exceptions gracefully with specific error messages
- Use logging instead of print statements for debugging
- Maintain test coverage for new functionality

## Dependencies & Tools
### Core Dependencies
- GitPython, PyGithub for Git operations
- typer, rich for CLI interface
- transformers, huggingface-hub for AI model handling
- uv for fast package management

### Development Tools
- **Linting**: ruff (configured in pyproject.toml)
- **Testing**: pytest with coverage
- **Pre-commit**: pre-commit hooks for code quality
- **Type Checking**: Use type hints, consider mypy for strict checking

## File Organization
- Keep business logic in appropriate modules under `glob/`
- Place utility functions in `common/` for reusability
- Store UI/frontend code in `js/` directory
- Maintain documentation in `docs/` with multilingual support

### Large Data Files Policy
- **NEVER read .json files directly** - These contain large datasets that cause unnecessary token consumption
- Use `JSON_REFERENCE.md` for understanding JSON file structures and schemas
- Work with processed/filtered data through APIs when possible
- For structure analysis, refer to data models in `comfyui_manager/data_models/` instead

## Git Workflow
- Work on feature branches, not main directly
- Write clear, descriptive commit messages
- Run tests and linting before committing
- Keep commits atomic and focused

## Testing Requirements

### ⚠️ Critical: Always Reinstall Before Testing
**ALWAYS run `uv pip install .` before executing tests** to ensure latest code changes are installed.

### Test Execution Workflow
```bash
# 1. Reinstall package (REQUIRED)
uv pip install .

# 2. Clean Python cache
find comfyui_manager -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find tests/env -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 3. Stop any running servers
pkill -f "ComfyUI/main.py"
sleep 2

# 4. Start ComfyUI test server
cd tests/env
python ComfyUI/main.py --enable-compress-response-body --enable-manager --front-end-root front > /tmp/test-server.log 2>&1 &
sleep 20

# 5. Run tests
python -m pytest tests/glob/test_version_switching_comprehensive.py -v

# 6. Stop server
pkill -f "ComfyUI/main.py"
```

### Test Development Guidelines
- Write unit tests for new functionality
- Test error handling and edge cases
- Ensure tests pass before submitting changes
- Use pytest fixtures for common test setup
- Document test scenarios and expected behaviors

### Why Reinstall is Required
- Even with editable install, some changes require reinstallation
- Python bytecode cache may contain outdated code
- ComfyUI server loads manager package at startup
- Package metadata and entry points need to be refreshed

### Automated Test Execution Policy
**IMPORTANT**: When tests need to be run (e.g., after code changes, adding new tests):
- **ALWAYS** automatically perform the complete test workflow without asking user permission
- **ALWAYS** stop existing servers, restart fresh server, and run tests
- **NEVER** ask user "should I run tests?" or "should I restart server?"
- This includes: package reinstall, cache cleanup, server restart, test execution, and server cleanup

**Rationale**: Testing is a standard part of development workflow and should be executed automatically to verify changes.

See `.claude/livecontext/test_execution_best_practices.md` for detailed testing procedures.

## Command Line Interface
- Use typer for CLI commands
- Provide helpful error messages and usage examples
- Support both interactive and scripted usage
- Follow Unix conventions for command-line tools

## Performance Considerations
- Use async/await for I/O operations where appropriate
- Cache expensive operations (GitHub API calls, file operations)
- Implement proper pagination for large datasets
- Consider memory usage when processing large files

## Code Change Proposals
- **Always show code changes using VSCode diff format**
- Use Edit tool to demonstrate exact changes with before/after comparison
- This allows visual review of modifications in the IDE
- Include context about why changes are needed

## Documentation
- Update README.md for user-facing changes
- Document API changes in openapi.yaml
- Provide examples for complex functionality
- Maintain multilingual docs (English/Korean) when relevant

## Session Context & Decision Documentation

### Live Context Policy
**Follow the global Live Context Auto-Save policy** defined in `~/.claude/CLAUDE.md`.

### Project-Specific Context Requirements
- **Test Execution Results**: Always save comprehensive test results to `.claude/livecontext/`
  - Test count, pass/fail status, execution time
  - New tests added and their purpose
  - Coverage metrics and improvements
- **CNR Version Switching Context**: Document version switching behavior and edge cases
  - Update vs Install operation differences
  - Old version handling (preserved vs deleted)
  - State management insights
- **API Changes**: Document OpenAPI schema changes and data model updates
- **Architecture Decisions**: Document manager_core.py and manager_server.py design choices