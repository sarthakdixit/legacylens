# Legacy Code Audit CLI — Requirements

> **Status:** Draft v0.1 · Requirements gathering · 2026-06-30
> **Owner:** sarthadixit@deloitte.com

A security- & compliance-first CLI that ingests legacy code, builds dependency
graphs, flags security vulnerabilities, and generates modern documentation —
running fully **on-prem / air-gapped** with **bring-your-own LLM**.

---

## 1. Vision & scope

An AI-assisted **legacy code analysis tool**, delivered as a **CLI**. A user points
it at a codebase (starting with mainframe sources). A pluggable LLM pipeline then:

1. **Maps dependency graphs** — call graphs, data flow, and cross-artifact relationships.
2. **Flags security & compliance issues** — mapped to **CWE / OWASP** (extensible).
3. **Generates modern documentation** — human-readable explanations of legacy logic.

All three outputs are **co-equal v1 priorities**.

---

## 2. Confirmed decisions

| Area | Decision |
|---|---|
| **Deployment** | On-prem / **air-gapped**. No code or telemetry leaves the client environment. |
| **Form factor** | **CLI** (highly customizable / config-driven). |
| **LLM strategy** | **Bring-your-own**: clients use their own self-hosted models *or* their own LLM API keys. Provider-agnostic abstraction. |
| **Target languages (v1)** | Mainframe: **COBOL, JCL, PL/I**. |
| **Core outputs** | Dependency graphs · Security/compliance findings · Modern docs — **all equal**. |
| **Implementation language** | **Python**. |
| **Compliance mapping** | **CWE / OWASP** (designed to extend to NIST/CIS/regulatory + custom rule packs later). |
| **Output formats** | **User-selectable, multiple formats** (pluggable emitters). |
| **Scale target** | **Large: 500k–millions LOC**. Persistent index, incremental analysis, cost control required. |

---

## 3. Functional requirements

### 3.1 Ingestion
- FR-1 Accept a directory / archive of source files; recursive discovery.
- FR-2 Detect & classify artifacts (COBOL programs/copybooks, JCL, PL/I, plus unknown).
- FR-3 Support large estates incrementally — index once, re-analyze only changed files.
- FR-4 Never transmit source externally in air-gapped mode (hard guarantee + verifiable).

### 3.2 Parsing & dependency graph
- FR-5 Parse each language to a structural representation (grammar-based where possible, LLM-assisted fallback).
- FR-6 Resolve cross-artifact links: `CALL`, `COPY`/copybooks, JCL→program, program→DB, file I/O.
- FR-7 Produce a queryable dependency graph (nodes = artifacts/paragraphs/jobs; edges = call/data/include).
- FR-8 Detect dead code, circular dependencies, and orphaned artifacts.

### 3.3 Security & compliance analysis
- FR-9 Flag vulnerabilities and risky patterns; classify each with **CWE ID** and **OWASP** category.
- FR-10 Detect hardcoded secrets/credentials and sensitive-data handling.
- FR-11 Each finding carries: severity, location (file:line), evidence, rationale, remediation guidance, confidence.
- FR-12 Compliance mappings are **config-driven rule packs** (CWE/OWASP shipped; custom packs loadable).
- FR-13 Deterministic findings (pattern/rule) separated from LLM-inferred findings; both labeled by source.

### 3.4 Documentation generation
- FR-14 Generate per-artifact docs: purpose, inputs/outputs, business logic summary, dependencies.
- FR-15 Generate system-level overview from the dependency graph.
- FR-16 Docs cite source locations; flag low-confidence inferences.

### 3.5 LLM abstraction (BYO)
- FR-17 Provider-agnostic interface: OpenAI-compatible endpoints, Anthropic, local servers (Ollama/vLLM/llama.cpp), etc.
- FR-18 Per-task model routing (e.g. cheap/local for bulk parsing, stronger model for synthesis) — all client-configured.
- FR-19 Credentials/endpoints supplied via config/env; never hardcoded; redacted from logs.
- FR-20 Graceful behavior when a model/context limit is hit (chunking, retry, degrade).

### 3.6 Output / reporting
- FR-21 Multiple **selectable** output formats per run, pluggable emitters. Candidates:
  - Machine-readable: **SARIF / JSON**
  - Human report: **HTML / PDF**
  - Graphs: **DOT / Mermaid / GraphML**
  - Docs: **Markdown**
- FR-22 Outputs are reproducible and audit-traceable (run metadata, model used, rule-pack versions).

### 3.7 CLI UX
- FR-23 Subcommands: e.g. `init`, `index`, `analyze`, `report`, `graph`, `doc`.
- FR-24 Project config file (e.g. `audit.yaml`): languages, model routing, rule packs, output formats, exclusions.
- FR-25 Resumable, incremental runs with progress; non-interactive/CI-friendly mode.

---

## 4. Non-functional requirements

- NFR-1 **Air-gap safe**: zero outbound network except to client-configured model endpoints; offline-installable.
- NFR-2 **Auditability**: every finding traceable to input + rule/model + version; run manifests stored.
- NFR-3 **Determinism where it matters**: rule-based checks reproducible; LLM steps record model/params/seed where available.
- NFR-4 **Scale**: handle millions of LOC via persistent index + chunked/retrieval-based context; bounded memory.
- NFR-5 **Cost/throughput control**: token budgeting, caching of LLM results keyed by content hash.
- NFR-6 **Security of the tool itself**: secret redaction, least-privilege file access, no temp leakage.
- NFR-7 **Extensibility**: new languages, rule packs, and output emitters are plugins.

---

## 5. Proposed architecture (high level)

```
                ┌──────────────┐
  source ──►    │  Ingestion   │  discover, classify, hash
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │   Parsers    │  per-language → structural model
                │ (grammar +   │
                │  LLM assist) │
                └──────┬───────┘
                       ▼
                ┌──────────────┐      ┌────────────────────┐
                │ Graph builder│◄────►│ Persistent index/DB │  (incremental)
                └──────┬───────┘      └────────────────────┘
                       ▼
        ┌──────────────┼──────────────┐
        ▼              ▼               ▼
  ┌──────────┐  ┌─────────────┐  ┌──────────────┐
  │ Security │  │ Dependency  │  │ Doc          │
  │ analyzer │  │ analytics   │  │ generator    │
  └────┬─────┘  └──────┬──────┘  └──────┬───────┘
       └───────────────┼────────────────┘
                       ▼
                ┌──────────────┐
                │ Output layer │  pluggable emitters (SARIF/HTML/DOT/MD/…)
                └──────────────┘

  Cross-cutting:  LLM Gateway (BYO providers, routing, caching) · Config · Audit log
```

---

## 6. Out of scope (v1)
- Automatic code remediation / refactoring (analysis & guidance only).
- Non-mainframe languages (planned later; architecture must not block them).
- Multi-tenant SaaS hosting; web UI (CLI only for v1).
- Runtime/dynamic analysis (static analysis only).

---

## 7. Resolved decisions (was: open questions)
- **OQ-1 Parsing depth → RESOLVED: grammar-first, LLM fallback.** Use real COBOL/PL-I/JCL grammars (ANTLR/ProLeap-style) as the primary path for reliable, reproducible structure; LLM only fills gaps (unparseable dialects, ambiguous constructs) and is labeled as inferred.
- **OQ-2 Index backend → RESOLVED: embedded, zero-dependency.** SQLite + on-disk vectors. No external DB required (air-gap friendly).
- **OQ-3 Embeddings/RAG → RESOLVED: yes, BYO/local embeddings.** Semantic retrieval used for large-estate context; embedding model is also bring-your-own / local.
- **OQ-6 Determinism → RESOLVED: LLM findings are ADVISORY.** A human confirms LLM-inferred findings before they are authoritative. Rule/grammar-based findings remain deterministic; LLM findings carry confidence and a `requires_human_review` flag and never auto-pass audit on their own.
- **OQ-5 Packaging → RESOLVED: open source on GitHub.** Distributed as an open-source Python package via GitHub; installed in air-gapped envs by cloning/downloading a release and installing from offline wheels. Implies: permissive license (Apache-2.0/MIT TBD), no proprietary/client code in repo, public issue tracker.

### Still open
- **OQ-4 Compliance breadth at v1:** confirm **CWE/OWASP only** for v1, with custom rule packs as the extension path. *(Assumed yes unless you say otherwise.)*
- **OQ-7 Product name** (working dir is `ITC`). *(Need a name for the package/CLI command.)*
- **OQ-8 License:** Apache-2.0 (patent grant, enterprise-friendly) vs MIT. *(Recommend Apache-2.0.)*

---

## 8. Suggested milestones
1. **M0 – Skeleton:** CLI scaffold, config schema, LLM gateway with one BYO provider, audit log.
2. **M1 – Ingest + index:** discovery, classification, persistent incremental index.
3. **M2 – COBOL parse + graph:** structural model + dependency graph + one graph emitter.
4. **M3 – Security analysis:** CWE/OWASP rule packs + LLM-assisted findings + SARIF/HTML.
5. **M4 – Docs:** per-artifact + system docs in Markdown.
6. **M5 – Scale + JCL/PL-I:** incremental at scale, cost controls, remaining languages.
