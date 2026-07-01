# Changelog

All notable changes to legacylens are documented here. This project follows
[Semantic Versioning](https://semver.org/) and the
[Keep a Changelog](https://keepachangelog.com/) format.

## [0.1.0] — 2026-07-01

First public release. A security- and compliance-first, on-prem/air-gapped,
bring-your-own-LLM CLI for analyzing legacy/mainframe code.

### Added

**Pipeline & CLI**
- Commands: `init`, `index`, `analyze`, `graph`, `report`, `doc`, `embed`, `search`,
  `baseline`, `suppress`, `diff`, `compliance`, `doctor`.
- Global install via pipx (`scripts/install.ps1` / `install.sh`); `python -m legacylens`
  fallback; first-run dependency preflight that installs missing libs with consent.

**Ingestion & parsing**
- Recursive discovery, artifact classification (extension + content heuristics),
  incremental SQLite index keyed by content hash.
- COBOL parser (line/regex) with an optional **ANTLR** grammar backend
  (`parser.backend: antlr`); JCL and PL/I parsers.
- **EXEC CICS** (LINK/XCTL) and **EXEC SQL** extraction — CICS call graph + DB2 table
  dependencies.
- Content-addressed **parse cache** and **parallel** parse pre-warming (`-j`).

**Dependency graph**
- Call/copy/exec/dd/cics/sql edges; cycle, orphan, unused-copybook, and unresolved
  detection; DOT / Mermaid / GraphML output. Type-namespaced node keys.

**Security & compliance**
- Deterministic CWE/OWASP rule packs (secrets, JCL passwords, dynamic SQL, sensitive
  output, dynamic CALL/CICS, hard-coded IP, debug code, missing EVALUATE default,
  PL/I output).
- **Custom rule packs** (YAML) and **regulatory frameworks** (built-in PCI-DSS,
  NIST 800-53; custom via YAML) mapping findings to controls.
- Optional **LLM-advisory** findings, always flagged for human review.
- Findings lifecycle: **suppression**, **baseline/diff**, and **CI gating**
  (`--fail-on`, exit code 6). SARIF / JSON / HTML reports with fingerprints.

**Documentation**
- Per-artifact Markdown docs + system overview (embedded Mermaid graph, security
  summary, structural observations), with source citations.

**LLM gateway (BYO)**
- Provider-agnostic: OpenAI-compatible, Anthropic, and local servers; per-task
  routing; content-hash response cache; air-gap endpoint enforcement; token budget.
- Simple **`llm_config.yaml`** (url/model/key) as an easy alternative to a full
  `llm:` block; keys read from env vars, never stored.
- **Retrieval-augmented** documentation and security via a BYO-embeddings index.

### Validated
- Exercised on 10 public COBOL/JCL/PL-I repositories across two rounds plus a full
  client-style run; see `docs/VALIDATION.md`.

### Notes
- Built-in compliance control mappings are indicative; confirm against the current
  standard for a formal audit.
- The ANTLR backend requires a one-time `scripts/build_antlr.py` (Java at build time);
  it does not yet extract EXEC CICS/SQL blocks (the regex backend does).

[0.1.0]: https://github.com/your-org/legacylens/releases/tag/v0.1.0
