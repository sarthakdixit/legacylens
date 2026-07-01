# legacylens

> Security- and compliance-first CLI for AI-assisted legacy code analysis.

`legacylens` analyzes legacy/mainframe codebases (COBOL, JCL, PL/I) and produces
three co-equal outputs:

- **Dependency graphs** — call / copy / EXEC / CICS / SQL relationships across artifacts.
- **Security & compliance findings** — CWE/OWASP, mapped to regulatory controls
  (PCI-DSS, NIST). SARIF / JSON / HTML.
- **Modern documentation** — human-readable explanations of legacy logic.

Runs **on-prem / air-gapped** with **bring-your-own LLM** — your own local models or
API keys. No source or telemetry leaves your environment; the LLM is optional.

## Install

```bash
pipx install legacylens        # recommended (puts `legacylens` on PATH, all OSes)
# or:  pip install legacylens
legacylens --help
```

Air-gapped and dev installs are in [RELEASING.md](RELEASING.md) and
[docs](docs/). On first run, legacylens offers to install any missing libraries;
`legacylens doctor` reports environment status.

## Quick start

```bash
legacylens init            # scaffold audit.yaml; set project.root + languages
legacylens index           # discover & index sources
legacylens analyze         # parse + security/compliance findings
legacylens graph           # dependency graph (DOT / Mermaid / GraphML)
legacylens report          # findings as SARIF / JSON / HTML
legacylens doc             # Markdown docs + system overview
```

Add `--no-llm` to run fully deterministically (no model calls). `legacylens --help`
lists every command.

## Configure your LLM (optional)

Easiest: drop a **`llm_config.yaml`** next to `audit.yaml` (and omit the `llm:`
block) — legacylens auto-detects it:

```yaml
type: openai_compatible
url: https://generativelanguage.googleapis.com/v1beta/openai   # Gemini shown
model: gemini-2.0-flash
key: PASTE_YOUR_KEY_HERE       # or `api_key_env: GEMINI_API_KEY` to read from an env var
```

Works with OpenAI, Anthropic, Gemini, local (Ollama/vLLM), or any OpenAI-compatible
endpoint. Then run `analyze` / `doc` without `--no-llm`. Full reference:
[examples/llm_config.example.yaml](examples/llm_config.example.yaml) and
[examples/audit.example.yaml](examples/audit.example.yaml).

## Key features

- **Parsers** — COBOL (regex, or optional [ANTLR](docs/RULES.md) backend), JCL, PL/I;
  `EXEC CICS` (LINK/XCTL) and `EXEC SQL` → CICS call graph + DB2 table dependencies.
- **Findings workflow** — suppression, baseline/diff, and CI gating
  (`analyze --fail-on high`, exit code 6). Custom rule packs + regulatory frameworks;
  see [docs/RULES.md](docs/RULES.md).
- **BYO-LLM gateway** — provider-agnostic, per-task routing, response cache, token
  budget, air-gap endpoint enforcement. LLM findings/docs are advisory (flagged for
  review) and can be retrieval-augmented (`embed` + `search`).
- **Scale** — incremental content-addressed parse cache; parallel parsing (`-j`).

All behavior is driven by one config file (`audit.yaml`); keys are never stored in
config. Full commented schema: [examples/audit.example.yaml](examples/audit.example.yaml).

## Docs

- [docs/RULES.md](docs/RULES.md) — rule packs, custom packs, compliance frameworks
- [docs/VALIDATION.md](docs/VALIDATION.md) — results on public COBOL/JCL/PL-I repos
- [CHANGELOG.md](CHANGELOG.md) · [RELEASING.md](RELEASING.md) · [REQUIREMENTS.md](REQUIREMENTS.md)

## Development

```bash
python -m venv .venv && . .venv/Scripts/activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
