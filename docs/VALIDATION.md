# Validation — Integration Testing Against Public Repositories

> **Date:** 2026-06-30 · **Tool version:** 0.0.1 · **Mode:** fully offline (`--no-llm`)

This document records `legacylens` being exercised end-to-end against real, public
legacy codebases — not just the unit-test fixtures. The goal is to demonstrate the
tool works on genuine COBOL/JCL/PL-I at scale and to capture the issues that this
testing surfaced (and that were subsequently fixed).

For every repository the full pipeline was run:
`index → analyze → graph → report → doc`.

## Test matrix

| Category | Repository | Scale (indexed) | Graph | Result |
|---|---|---|---|---|
| **COBOL** | [aws-samples/aws-mainframe-modernization-carddemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) | 106 COBOL (44 prog / 62 copybook), 62 JCL | 291 nodes / 761 edges, 0 cycles | ✅ 10 findings (9 med, 1 low) |
| **COBOL** | [IBM/Bank-of-Z](https://github.com/IBM/Bank-of-Z) | 103 COBOL, 39 JCL, 2 PL/I | 179 nodes / 238 edges, 0 cycles | ✅ 6 findings (6 med); 37 unused copybooks flagged |
| **JCL** | [benjaminthompson1/JCL](https://github.com/benjaminthompson1/JCL) | 156 JCL (**extensionless PDS members**) | 326 nodes / 475 edges, 0 cycles | ✅ 6 findings (1 high, 5 low) |
| **JCL** | [IBM/zopeneditor-sample](https://github.com/IBM/zopeneditor-sample) | 13 COBOL, 10 JCL, 7 PL/I | 33 nodes / 57 edges, 0 cycles | ✅ 3 findings (3 med) |
| **PL/I** | [IBM/zopeneditor-sample](https://github.com/IBM/zopeneditor-sample) | (see above — multi-language sample) | — | ✅ clean PL/I parse (7 programs) |
| **PL/I** | [Steadsoft/PLI-2000](https://github.com/Steadsoft/PLI-2000) | 144 PL/I (compiler **torture-test** corpus) | 155 nodes / 885 edges, 0 cycles | ✅ parses; internal procedures resolved |
| **VULN** | *(no public vulnerable-COBOL repo exists)* | — | — | validated via real findings + bundled fixture (below) |

A concrete sample of real output is committed at
[docs/validation-samples/carddemo-findings.json](validation-samples/carddemo-findings.json)
(CardDemo's actual security findings).

Highlights:

- **Extensionless classification works.** `benjaminthompson1/JCL` stores raw PDS
  members in `CNTL/` with no file extension; the content-based classifier correctly
  identified 156 of them as JCL.
- **Real, legitimate security findings.** On CardDemo the tool flagged 8 `DISPLAY`
  statements that emit card numbers / card records to logs (CWE-532 — a genuine
  PCI-DSS concern, e.g. `DISPLAY 'CARD NUMBER ' DALYTRAN-CARD-NUM`), a dynamic
  `CALL`, and a hard-coded IP address in a JCL FTP step. The JCL corpus flagged a
  hard-coded `PASSWORD=` (CWE-798, high).
- **Scale.** CardDemo + Bank-of-Z together parsed ~16,000 data items and ~1,800
  paragraphs without issue; runs complete in seconds.

## Issues found and fixed during this testing

Real codebases exposed precision/correctness bugs that the clean unit fixtures could
not. Each was fixed with a regression test:

| Issue | Surfaced on | Fix (commit) |
|---|---|---|
| `CALL`/`COPY` matched inside COBOL string literals; `IMS-CALL` suffix matched as `CALL` | CardDemo | `1b13d3b` |
| Security rules flagged keywords inside message literals (`'Please enter Password'`, `'ERROR READING CARDFILE'`) | CardDemo | `1b13d3b` |
| `EXEC` self-edge (job runs same-named program) reported as a dependency cycle | CardDemo | `1b13d3b` |
| Job and same-named program collapsed into one node | CardDemo | `1e1887c` |
| Absolute local paths leaked into documentation citations | CardDemo | `f64fd74` |
| `CALL` matched inside PL/I string literals | PLI-2000 | `5fec67f` |
| PL/I internal-procedure calls modeled as cross-program edges | zopeneditor / PLI-2000 | `5fec67f` |
| Copybook and same-named program (CICS commarea copybooks) collapsed into one node, creating false `COPY` cycles | Bank-of-Z | `5fec67f` |
| PL/I procedures with the label on a separate line (`run_inner_proc:` \n `proc;`) went undetected, so internal calls leaked as unresolved cross-program edges | PLI-2000 | `9d97d1d` |

Net effect: noisy findings/cycles were eliminated while genuine signal was retained
(e.g. CardDemo 32 → 10 findings; Bank-of-Z 11 → 0 false cycles).

## Security ("VULN") validation

There is **no well-known public repository of deliberately-vulnerable COBOL** (the
ecosystem has no "DVWA for COBOL"). Security detection is therefore validated by:

1. **Genuine vulnerabilities in the real corpora above** — sensitive-data exposure
   via `DISPLAY` (CWE-532) in CardDemo, a hard-coded `PASSWORD=` in the JCL corpus
   (CWE-798), and a hard-coded IP address.
2. **A bundled deliberately-vulnerable fixture** — [tests/fixtures/vuln/](../tests/fixtures/vuln)
   (`VULN.cbl`, `VULNJOB.jcl`) covering CWE-798, CWE-89, CWE-532, and CWE-94, asserted
   by [tests/test_security.py](../tests/test_security.py).

## EXEC CICS / EXEC SQL support

Multi-repo testing revealed that CICS programs transfer control via
`EXEC CICS LINK/XCTL PROGRAM(...)` rather than COBOL `CALL`, and reach data via
`EXEC SQL` — neither of which the parser originally recognized, so the dependency
graph for CICS/DB2 applications was materially incomplete. The COBOL parser now
extracts both. Re-validated on **IBM/Bank-of-Z** (a CICS/DB2 app):

| Edge type | Before | After |
|---|---|---|
| `cics` (LINK/XCTL program transfer) | 0 | **140** |
| `sql` (program → DB2 table) | 0 | **52** (across 5 table nodes) |
| total graph edges | 238 | **430** |

CICS transfers participate in cycle and orphan analysis (a CICS-linked program is
not an orphan); SQL table access is a data dependency and is excluded from cycles.
Host variables (`:WS-VAR`) are not mistaken for tables.

> Note: EXEC CICS/SQL extraction is implemented in the default **regex** backend.
> The optional ANTLR backend does not yet recognize EXEC blocks (a grammar
> enhancement) — another reason regex remains the default.

## ANTLR parser backend validation

The optional ANTLR COBOL backend (`parser.backend: antlr`) was generated
(`scripts/build_antlr.py`) and run against the COBOL corpora, head-to-head with the
default regex backend:

| Repo | COBOL files | Paragraphs (regex → antlr) | CALL | COPY |
|---|---|---|---|---|
| CardDemo | 106 | 1051 → **1051** | 64 → 64 | 337 → 337 |
| Bank-of-Z | 103 | 786 → **786** | 44 → 44 | 120 → 120 |
| zopeneditor-sample | 13 | 87 → **87** | 3 → 3 | 21 → 21 |

Across **222 COBOL files the ANTLR backend ran without errors** and reached exact
parity with the regex parser on paragraphs, CALL, and COPY; data-item counts agree
to within ~1%. Getting there surfaced (and fixed) a few issues:

| Issue | Fix |
|---|---|
| ANTLR-parsed artifacts were reported as "used the LLM fallback (inferred)" | reporting now keys on the `+llm` method, not "≠ grammar" |
| Starter grammar's `NAME '.'` over-matched sentence endings as paragraphs | anchored paragraph labels to line starts (`NL NAME DOT`) |
| Verb labels (`EXIT.`, `GOBACK.`) and ID/ENV headers (`AUTHOR.`) counted as paragraphs | listener tracks the division and applies the same verb blocklist as the regex parser |

## Parse cache (incremental performance)

Parse results are cached in the index, content-addressed by (backend, kind,
sha256). On CardDemo (106 COBOL artifacts):

| Run | Real parses | Cache |
|---|---|---|
| Cold (first `analyze`) | 106 | 106 hits (security pass reuses the structural parse instead of re-parsing) |
| Warm (re-run, no changes) | **0** | 212 hits, 0 misses |

Before this, `analyze` parsed every file twice (structural + security) and `graph`/
`doc` re-parsed from scratch. Now unchanged files are parsed once and reused across
passes, commands, and runs — the basis for incremental analysis at scale.

## Notes

- **PLI-2000** is a PL/I *compiler conformance / torture-test* suite, not
  representative business PL/I. After the separate-line procedure-detection fix
  (`9d97d1d`), internal calls resolve correctly and the graph has no cycles; edges
  dropped 1098 → 885 and unresolved references 40 → 15. The residual edges and
  unresolved names are genuine — the corpus is made of standalone fragments that
  reference truly-external entries — so they are reported accurately rather than
  suppressed.

## Reproducing

```bash
git clone --depth 1 <repo-url> target
legacylens init                 # edit audit.yaml: root -> ./target, languages
legacylens index
legacylens analyze --no-llm
legacylens graph
legacylens report
legacylens doc --no-llm
# outputs in ./<output.dir>/  (report.html, sarif.json, graph.mmd, docs/)
```
