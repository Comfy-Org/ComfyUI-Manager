# ComfyUI Manager Documentation Index

**Last Updated**: 2025-11-04
**Purpose**: Navigate all project documentation organized by purpose and audience

---

## 📖 Quick Links

- **Getting Started**: [README.md](README.md)
- **User Documentation**: [docs/](docs/)
- **Test Documentation**: [tests/glob/](tests/glob/)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Development**: [CLAUDE.md](CLAUDE.md)

---

## 📚 Documentation Structure

### Root Level

| Document | Purpose | Audience |
|----------|---------|----------|
| [README.md](README.md) | Project overview and quick start | Everyone |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines | Contributors |
| [CLAUDE.md](CLAUDE.md) | Development guidelines for AI-assisted development | Developers |
| [JSON_REFERENCE.md](JSON_REFERENCE.md) | JSON file schema reference | Developers |

### User Documentation (`docs/`)

| Document | Purpose | Language |
|----------|---------|----------|
| [docs/README.md](docs/README.md) | Documentation overview | English |
| [docs/PACKAGE_VERSION_MANAGEMENT.md](docs/PACKAGE_VERSION_MANAGEMENT.md) | Package version management guide | English |
| [docs/SECURITY_ENHANCED_INSTALLATION.md](docs/SECURITY_ENHANCED_INSTALLATION.md) | Security features for URL installation | English |
| [docs/en/cm-cli.md](docs/en/cm-cli.md) | CLI usage guide | English |
| [docs/en/use_aria2.md](docs/en/use_aria2.md) | Aria2 download configuration | English |
| [docs/ko/cm-cli.md](docs/ko/cm-cli.md) | CLI usage guide | Korean |

### Package Documentation

| Package | Document | Purpose |
|---------|----------|---------|
| comfyui_manager | [comfyui_manager/README.md](comfyui_manager/README.md) | Package overview |
| common | [comfyui_manager/common/README.md](comfyui_manager/common/README.md) | Common utilities documentation |
| data_models | [comfyui_manager/data_models/README.md](comfyui_manager/data_models/README.md) | Data model generation guide |
| glob | [comfyui_manager/glob/CLAUDE.md](comfyui_manager/glob/CLAUDE.md) | Glob module development guide |
| js | [comfyui_manager/js/README.md](comfyui_manager/js/README.md) | JavaScript components |

### Test Documentation (`tests/`)

| Document | Purpose | Status |
|----------|---------|--------|
| [tests/TEST.md](tests/TEST.md) | Testing overview | ✅ |
| [tests/glob/README.md](tests/glob/README.md) | Glob API endpoint tests | ✅ Translated |
| [tests/glob/TESTING_GUIDE.md](tests/glob/TESTING_GUIDE.md) | Test execution guide | ✅ |
| [tests/glob/TEST_INDEX.md](tests/glob/TEST_INDEX.md) | Test documentation unified index | ✅ Translated |
| [tests/glob/TEST_LOG.md](tests/glob/TEST_LOG.md) | Test execution log | ✅ Translated |

### Node Database

| Document | Purpose |
|----------|---------|
| [node_db/README.md](node_db/README.md) | Node database information |

---

## 🔒 Internal Documentation (`docs/internal/`)

### CLI Migration (`docs/internal/cli_migration/`)

Historical documentation for CLI migration from legacy to glob module (completed).

| Document | Purpose |
|----------|---------|
| [README.md](docs/internal/cli_migration/README.md) | Migration plan overview |
| [CLI_COMPATIBILITY_ANALYSIS.md](docs/internal/cli_migration/CLI_COMPATIBILITY_ANALYSIS.md) | Legacy vs Glob compatibility analysis |
| [CLI_IMPLEMENTATION_CONTEXT.md](docs/internal/cli_migration/CLI_IMPLEMENTATION_CONTEXT.md) | Implementation context |
| [CLI_IMPLEMENTATION_TODO.md](docs/internal/cli_migration/CLI_IMPLEMENTATION_TODO.md) | Implementation checklist |
| [CLI_PURE_GLOB_MIGRATION_PLAN.md](docs/internal/cli_migration/CLI_PURE_GLOB_MIGRATION_PLAN.md) | Technical migration specification |
| [CLI_GLOB_API_REFERENCE.md](docs/internal/cli_migration/CLI_GLOB_API_REFERENCE.md) | Glob API reference |
| [CLI_IMPLEMENTATION_CONSTRAINTS.md](docs/internal/cli_migration/CLI_IMPLEMENTATION_CONSTRAINTS.md) | Migration constraints |
| [CLI_TESTING_CHECKLIST.md](docs/internal/cli_migration/CLI_TESTING_CHECKLIST.md) | Testing checklist |
| [CLI_SHOW_LIST_REVISION.md](docs/internal/cli_migration/CLI_SHOW_LIST_REVISION.md) | show_list implementation plan |

### Test Planning (`docs/internal/test_planning/`)

Internal test planning documents (in Korean).

| Document | Purpose | Language |
|----------|---------|----------|
| [TEST_PLAN_ADDITIONAL.md](docs/internal/test_planning/TEST_PLAN_ADDITIONAL.md) | Additional test scenarios | Korean |
| [COMPLEX_SCENARIOS_TEST_PLAN.md](docs/internal/test_planning/COMPLEX_SCENARIOS_TEST_PLAN.md) | Complex multi-version test scenarios | Korean |

---

## 📋 Documentation by Audience

### For Users
1. [README.md](README.md) - Start here
2. [docs/en/cm-cli.md](docs/en/cm-cli.md) - CLI usage
3. [docs/PACKAGE_VERSION_MANAGEMENT.md](docs/PACKAGE_VERSION_MANAGEMENT.md) - Version management

### For Contributors
1. [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution process
2. [CLAUDE.md](CLAUDE.md) - Development guidelines
3. [comfyui_manager/data_models/README.md](comfyui_manager/data_models/README.md) - Data model workflow

### For Developers
1. [CLAUDE.md](CLAUDE.md) - Development workflow
2. [comfyui_manager/glob/CLAUDE.md](comfyui_manager/glob/CLAUDE.md) - Glob module guide
3. [JSON_REFERENCE.md](JSON_REFERENCE.md) - Schema reference
4. [docs/PACKAGE_VERSION_MANAGEMENT.md](docs/PACKAGE_VERSION_MANAGEMENT.md) - Package management internals

### For Testers
1. [tests/TEST.md](tests/TEST.md) - Testing overview
2. [tests/glob/TEST_INDEX.md](tests/glob/TEST_INDEX.md) - Test documentation index
3. [tests/glob/TESTING_GUIDE.md](tests/glob/TESTING_GUIDE.md) - Test execution guide

---

## 🔄 Documentation Maintenance

### When to Update
- **README.md**: Project structure or main features change
- **CLAUDE.md**: Development workflow changes
- **Test Documentation**: New tests added or test structure changes
- **User Documentation**: User-facing features change
- **This Index**: New documentation added or reorganized

### Documentation Standards
- Use clear, descriptive titles
- Include "Last Updated" date
- Specify target audience
- Provide examples where applicable
- Keep language simple and accessible
- Translate user-facing docs to Korean when possible

---

## 🗂️ File Organization

```
comfyui-manager/
├── DOCUMENTATION_INDEX.md (this file)
├── README.md
├── CONTRIBUTING.md
├── CLAUDE.md
├── JSON_REFERENCE.md
├── docs/
│   ├── README.md
│   ├── PACKAGE_VERSION_MANAGEMENT.md
│   ├── SECURITY_ENHANCED_INSTALLATION.md
│   ├── en/
│   │   ├── cm-cli.md
│   │   └── use_aria2.md
│   ├── ko/
│   │   └── cm-cli.md
│   └── internal/
│       ├── cli_migration/       (9 files - completed migration docs)
│       └── test_planning/       (2 files - Korean test plans)
├── comfyui_manager/
│   ├── README.md
│   ├── common/README.md
│   ├── data_models/README.md
│   ├── glob/CLAUDE.md
│   └── js/README.md
├── tests/
│   ├── TEST.md
│   └── glob/
│       ├── README.md
│       ├── TESTING_GUIDE.md
│       ├── TEST_INDEX.md
│       └── TEST_LOG.md
└── node_db/
    └── README.md
```

---

**Total Documentation Files**: 36 files organized across 6 categories

**Translation Status**:
- ✅ Core user documentation: English
- ✅ CLI guide: English + Korean
- ✅ Test documentation: English (translated from Korean)
- 📝 Internal planning docs: Korean (preserved as-is for historical reference)
