"""legacylens command-line interface.

Subcommands map to the analysis pipeline stages:

    init      scaffold an audit.yaml in the current directory
    index     discover & index sources into the persistent store      (B2)
    analyze   run parsing + security/compliance analysis               (B3, B5)
    graph     emit the dependency graph                                (B4)
    doc       generate modern documentation                           (B6)
    report    render selected output formats from analysis results    (B5)

In B0 only `init` is functional; the remaining commands validate config and the
runtime context, then report that their stage is not yet implemented. This keeps
the CLI contract stable while later batches fill in behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .audit_log import AuditLog
from .config import DEFAULT_CONFIG_NAME, Config, OutputFormat, load_config
from .docs import DocGenerator
from .errors import LegacyLensError
from .graph import build_graph, to_dot, to_graphml, to_mermaid
from .ingest import Indexer
from .llm import build_gateway
from .logging_setup import get_logger, setup_logging
from .parsing import JclParser, PliParser, build_cobol_parser
from .retrieval import Retriever
from .security import Finding, SecurityAnalyzer, to_html, to_json, to_sarif
from .security.emit import summarize
from .store import IndexStore

CONFIG_TEMPLATE = """\
# legacylens project configuration
# Docs: https://github.com/your-org/legacylens
version: 1

project:
  name: my-legacy-system
  root: ./src

# Languages to analyze (v1: cobol, jcl, pli)
languages:
  - cobol

# Glob patterns to skip
exclude:
  - "**/test/**"

# Bring-your-own LLM. Credentials are read from the named environment variables;
# they are never stored in this file. In air-gapped mode only the endpoints below
# may be contacted.
llm:
  providers:
    - name: local
      type: local
      base_url: http://localhost:11434/v1
      model: qwen2.5-coder:32b
      api_key_env: LEGACYLENS_LOCAL_KEY
  routing:
    default: local
    # parse_fallback: local
    # security: local
    # documentation: local
  # embeddings:
  #   provider: local
  #   model: nomic-embed-text

analysis:
  compliance:
    rule_packs:
      - cwe
      - owasp

# COBOL parser backend: "regex" (default, zero-dependency) or "antlr" (grammar-based;
# requires a one-time `python scripts/build_antlr.py` build + the `antlr` extra).
parser:
  backend: regex
  fallback_to_regex: true

index:
  path: .legacylens/index.db

output:
  formats:
    - sarif
    - markdown
  dir: legacylens-out

audit:
  log_path: .legacylens/audit.log

# Hard ceiling on total LLM tokens per run (omit / null = unlimited).
budget:
  max_tokens: null

# Refuse any network endpoint not listed under llm.providers above.
air_gapped: true
"""


class Context:
    """Shared state passed to subcommands via click's context object."""

    def __init__(self, config_path: Path, verbose: bool):
        self.config_path = config_path
        self.verbose = verbose
        self._config: Config | None = None

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config(self.config_path)
        return self._config

    def audit_log(self) -> AuditLog:
        return AuditLog(self.config.audit.log_path)


pass_ctx = click.make_pass_decorator(Context)


def _cobol_parser(config: Config, gateway=None):
    """Build the COBOL parser for the client-selected backend (regex/antlr)."""
    return build_cobol_parser(
        config.parser.backend.value,
        gateway=gateway,
        fallback_to_regex=config.parser.fallback_to_regex,
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="legacylens")
@click.option(
    "-c",
    "--config",
    "config_path",
    default=DEFAULT_CONFIG_NAME,
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the legacylens config file.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug-level console logging.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path, verbose: bool) -> None:
    """legacylens — security- and compliance-first legacy code analysis."""
    setup_logging(verbose=verbose)
    ctx.obj = Context(config_path=config_path, verbose=verbose)


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite an existing config file.")
@pass_ctx
def init(ctx: Context, force: bool) -> None:
    """Scaffold a starter config file in the current directory."""
    log = get_logger()
    target = ctx.config_path
    if target.exists() and not force:
        raise LegacyLensError(
            f"{target} already exists. Use --force to overwrite."
        )
    target.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    log.info("Wrote starter config to %s", target)
    log.info("Edit it, then run `legacylens index` to begin.")


@cli.command()
@pass_ctx
def index(ctx: Context) -> None:
    """Discover and index source artifacts into the persistent store."""
    log = get_logger()
    config = ctx.config
    root = config.project.root
    if not root.exists():
        raise LegacyLensError(f"project.root does not exist: {root}")

    store = IndexStore(config.index.path)
    try:
        indexer = Indexer(store, [lang.value for lang in config.languages])
        stats = indexer.index(root, config.exclude)
    finally:
        store.close()

    ctx.audit_log().record(
        "index",
        project=config.project.name,
        root=str(root),
        added=stats.added,
        updated=stats.updated,
        unchanged=stats.unchanged,
        removed=stats.removed,
        skipped_unknown=stats.skipped_unknown,
        skipped_disabled=stats.skipped_disabled,
        by_language=stats.by_language,
    )

    log.info(
        "Indexed %s artifact(s): %s added, %s updated, %s unchanged, %s removed.",
        stats.scanned,
        stats.added,
        stats.updated,
        stats.unchanged,
        stats.removed,
    )
    if stats.by_language:
        breakdown = ", ".join(f"{lang}={n}" for lang, n in sorted(stats.by_language.items()))
        log.info("By language: %s", breakdown)
    if stats.skipped_unknown or stats.skipped_disabled:
        log.info(
            "Skipped %s unknown and %s out-of-scope file(s).",
            stats.skipped_unknown,
            stats.skipped_disabled,
        )
    log.info("Index stored at %s", config.index.path)


@cli.command()
@click.option("--no-llm", is_flag=True, help="Disable the LLM fallback for unparseable sources.")
@pass_ctx
def analyze(ctx: Context, no_llm: bool) -> None:
    """Parse sources and run security/compliance analysis."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` first.")

    store = IndexStore(config.index.path)
    gateway = None if no_llm else build_gateway(config)
    parser = _cobol_parser(config, gateway)
    try:
        artifacts = store.list_artifacts("cobol")
        totals = {
            "programs": 0,
            "copybooks": 0,
            "paragraphs": 0,
            "calls": 0,
            "copies": 0,
            "data_items": 0,
            "low_confidence": 0,
            "llm_assisted": 0,
            "jcl_jobs": 0,
            "jcl_steps": 0,
            "pli_programs": 0,
            "pli_procedures": 0,
        }
        for art in artifacts:
            try:
                text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("could not read %s: %s", art.rel_path, exc)
                continue
            result = parser.parse(text, source_path=art.abs_path, kind=art.kind)
            prog = result.program
            if prog.is_copybook:
                totals["copybooks"] += 1
            else:
                totals["programs"] += 1
            totals["paragraphs"] += len(prog.paragraphs)
            totals["calls"] += len(prog.calls)
            totals["copies"] += len(prog.copies)
            totals["data_items"] += len(prog.data_items)
            if result.confidence < 0.5:
                totals["low_confidence"] += 1
            if "llm" in result.method:  # e.g. "grammar+llm" — not the ANTLR backend
                totals["llm_assisted"] += 1

        # JCL and PL/I structural counts.
        jcl_parser, pli_parser = JclParser(), PliParser()
        for art in store.iter_artifacts("jcl"):
            text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
            job = jcl_parser.parse(text, fallback_name=Path(art.rel_path).stem)
            totals["jcl_jobs"] += 1
            totals["jcl_steps"] += len(job.steps)
        for art in store.iter_artifacts("pli"):
            text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
            p = pli_parser.parse(text, fallback_name=Path(art.rel_path).stem)
            totals["pli_programs"] += 1
            totals["pli_procedures"] += len(p.procedures)

        # Security & compliance analysis (deterministic rules + optional LLM advisory).
        analyzer = SecurityAnalyzer(
            config.analysis.compliance.rule_packs, gateway=gateway, parser=parser
        )
        findings = analyzer.analyze_estate(store)
        store.replace_findings([f.to_dict() for f in findings])
        sec_summary = summarize(findings)
        tokens_spent = gateway.tokens_spent if gateway is not None else 0
    finally:
        if gateway is not None:
            gateway.close()
        store.close()

    ctx.audit_log().record(
        "analyze",
        project=config.project.name,
        language="cobol",
        rule_packs=config.analysis.compliance.rule_packs,
        findings_total=sec_summary["total"],
        findings_by_severity=sec_summary["by_severity"],
        findings_by_source=sec_summary["by_source"],
        findings_requiring_review=sec_summary["requires_human_review"],
        tokens_spent=tokens_spent,
        **totals,
    )

    if artifacts:
        log.info(
            "Parsed %s COBOL artifact(s): %s program(s), %s copybook(s).",
            len(artifacts),
            totals["programs"],
            totals["copybooks"],
        )
        log.info(
            "Structure: %s paragraph(s), %s CALL(s), %s COPY(s), %s data item(s).",
            totals["paragraphs"],
            totals["calls"],
            totals["copies"],
            totals["data_items"],
        )
        if totals["low_confidence"]:
            log.warning("%s artifact(s) parsed with low confidence.", totals["low_confidence"])
        if totals["llm_assisted"]:
            log.info("%s artifact(s) used the LLM fallback (results flagged inferred).", totals["llm_assisted"])
    else:
        log.warning("No COBOL artifacts in the index.")

    if totals["jcl_jobs"]:
        log.info("JCL: %s job(s), %s step(s).", totals["jcl_jobs"], totals["jcl_steps"])
    if totals["pli_programs"]:
        log.info("PL/I: %s program(s), %s procedure(s).", totals["pli_programs"], totals["pli_procedures"])
    if tokens_spent:
        log.info("LLM tokens spent: %s.", tokens_spent)

    # Security summary.
    sev = sec_summary["by_severity"]
    log.info(
        "Security: %s finding(s) [%s] — %s require human review.",
        sec_summary["total"],
        ", ".join(f"{k}={v}" for k, v in sorted(sev.items(), reverse=True)) or "none",
        sec_summary["requires_human_review"],
    )
    log.info("Run `legacylens report` to render SARIF/JSON/HTML.")


_GRAPH_EMITTERS = {
    OutputFormat.dot: ("dot", to_dot),
    OutputFormat.mermaid: ("mmd", to_mermaid),
    OutputFormat.graphml: ("graphml", to_graphml),
}


@cli.command()
@pass_ctx
def graph(ctx: Context) -> None:
    """Build and emit the dependency graph."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` first.")

    store = IndexStore(config.index.path)
    try:
        dep_graph = build_graph(store, _cobol_parser(config))
    finally:
        store.close()

    # Emit the graph-capable formats the user selected; default to mermaid + dot.
    selected = [fmt for fmt in config.output.formats if fmt in _GRAPH_EMITTERS]
    if not selected:
        selected = [OutputFormat.mermaid, OutputFormat.dot]

    config.output.dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in selected:
        ext, emitter = _GRAPH_EMITTERS[fmt]
        out_path = config.output.dir / f"graph.{ext}"
        out_path.write_text(emitter(dep_graph), encoding="utf-8")
        written.append(str(out_path))

    cycles = dep_graph.find_cycles()
    orphans = dep_graph.orphans()
    unused = dep_graph.unused_copybooks()
    unresolved = dep_graph.unresolved_references()

    ctx.audit_log().record(
        "graph",
        project=config.project.name,
        nodes=len(dep_graph.nodes),
        edges=len(dep_graph.edges),
        cycles=len(cycles),
        orphans=orphans,
        unused_copybooks=unused,
        unresolved=unresolved,
        outputs=written,
    )

    log.info("Built graph: %s node(s), %s edge(s).", len(dep_graph.nodes), len(dep_graph.edges))
    if cycles:
        log.warning("%s dependency cycle(s) detected: %s", len(cycles), "; ".join(" -> ".join(c) for c in cycles))
    if orphans:
        log.warning("%s program(s) with no incoming references: %s", len(orphans), ", ".join(orphans))
    if unused:
        log.warning("%s unused copybook(s): %s", len(unused), ", ".join(unused))
    if unresolved:
        log.info("%s unresolved reference(s) (no source): %s", len(unresolved), ", ".join(unresolved))
    log.info("Wrote: %s", ", ".join(written))


def _doc_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return f"{safe}.md"


@cli.command()
@click.option("--no-llm", is_flag=True, help="Disable LLM prose; emit structural docs only.")
@pass_ctx
def doc(ctx: Context, no_llm: bool) -> None:
    """Generate modern documentation from analysis results."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` then `analyze` first.")

    store = IndexStore(config.index.path)
    gateway = None if no_llm else build_gateway(config)
    parser = _cobol_parser(config, gateway)
    generator = DocGenerator(gateway=gateway)
    docs_dir = config.output.dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_links: list[tuple[str, str, str]] = []
    written = []
    try:
        dep_graph = build_graph(store, parser)
        for art in store.list_artifacts("cobol"):
            try:
                text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("could not read %s: %s", art.rel_path, exc)
                continue
            result = parser.parse(text, source_path=art.abs_path, kind=art.kind)
            prog = result.program
            name = prog.program_id or Path(art.rel_path).stem.upper()
            md = generator.program_doc(prog, dep_graph, art.rel_path, result.confidence)
            filename = _doc_filename(name)
            (docs_dir / filename).write_text(md, encoding="utf-8")
            written.append(str(docs_dir / filename))
            doc_links.append((name, "copybook" if prog.is_copybook else "program", filename))

        findings_summary = summarize([Finding.from_dict(d) for d in store.list_findings()])
        overview_md = generator.overview(config.project.name, dep_graph, doc_links, findings_summary)
        (docs_dir / "OVERVIEW.md").write_text(overview_md, encoding="utf-8")
        written.append(str(docs_dir / "OVERVIEW.md"))
    finally:
        if gateway is not None:
            gateway.close()
        store.close()

    ctx.audit_log().record(
        "doc",
        project=config.project.name,
        artifacts_documented=len(doc_links),
        outputs=written,
    )
    log.info("Generated documentation for %s artifact(s) + overview.", len(doc_links))
    log.info("Docs written to %s", docs_dir)


_REPORT_EMITTERS = {
    OutputFormat.sarif: ("sarif.json", to_sarif),
    OutputFormat.json: ("findings.json", to_json),
    OutputFormat.html: ("report.html", to_html),
}


@cli.command()
@pass_ctx
def report(ctx: Context) -> None:
    """Render selected output formats from analysis results."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` then `analyze` first.")

    store = IndexStore(config.index.path)
    try:
        finding_dicts = store.list_findings()
    finally:
        store.close()

    if not finding_dicts:
        log.warning("No findings stored. Run `legacylens analyze` first.")
        return

    findings = [Finding.from_dict(d) for d in finding_dicts]

    # Emit the report formats the user selected; default to SARIF + JSON + HTML.
    selected = [fmt for fmt in config.output.formats if fmt in _REPORT_EMITTERS]
    if not selected:
        selected = [OutputFormat.sarif, OutputFormat.json, OutputFormat.html]

    config.output.dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in selected:
        filename, emitter = _REPORT_EMITTERS[fmt]
        out_path = config.output.dir / filename
        out_path.write_text(emitter(findings), encoding="utf-8")
        written.append(str(out_path))

    summary = summarize(findings)
    ctx.audit_log().record(
        "report",
        project=config.project.name,
        formats=[fmt.value for fmt in selected],
        findings_total=summary["total"],
        outputs=written,
    )
    log.info("Rendered %s finding(s) to: %s", summary["total"], ", ".join(written))


@cli.command()
@pass_ctx
def embed(ctx: Context) -> None:
    """Build the semantic embedding index (bring-your-own embeddings provider)."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` first.")
    if config.llm.embeddings is None:
        raise LegacyLensError("no embeddings provider configured (set llm.embeddings).")

    store = IndexStore(config.index.path)
    gateway = build_gateway(config)
    try:
        stats = Retriever(store, gateway).build([lang.value for lang in config.languages])
    finally:
        gateway.close()
        store.close()

    ctx.audit_log().record(
        "embed", project=config.project.name, embedded=stats.embedded, skipped=stats.skipped
    )
    log.info("Embedded %s artifact(s); %s unchanged (skipped).", stats.embedded, stats.skipped)


@cli.command()
@click.argument("query")
@click.option("-k", "--top", default=5, show_default=True, help="Number of results.")
@pass_ctx
def search(ctx: Context, query: str, top: int) -> None:
    """Find the artifacts most relevant to QUERY (requires `embed` first)."""
    log = get_logger()
    config = ctx.config
    if not config.index.path.exists():
        raise LegacyLensError("no index found — run `legacylens index` then `embed` first.")
    if config.llm.embeddings is None:
        raise LegacyLensError("no embeddings provider configured (set llm.embeddings).")

    store = IndexStore(config.index.path)
    gateway = build_gateway(config)
    try:
        hits = Retriever(store, gateway).search(query, k=top)
    finally:
        gateway.close()
        store.close()

    if not hits:
        log.warning("No embeddings found. Run `legacylens embed` first.")
        return
    for hit in hits:
        log.info("%.3f  %s", hit.score, hit.rel_path)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Converts expected errors into clean non-zero exits."""
    try:
        cli.main(args=argv, prog_name="legacylens", standalone_mode=False)
        return 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted.", err=True)
        return 130
    except LegacyLensError as exc:
        get_logger().error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
