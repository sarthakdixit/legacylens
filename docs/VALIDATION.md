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
| **PL/I** | [Steadsoft/PLI-2000](https://github.com/Steadsoft/PLI-2000) | 144 PL/I (compiler **torture-test** corpus) | 181 nodes / 1098 edges, 1 cycle | ⚠️ over-connected — see *Known limitations* |
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

## Known limitations (documented, not bugs)

- **PLI-2000** is a PL/I *compiler conformance / torture-test* suite, not
  representative business PL/I. Its files are fragments that the deliberately
  lightweight v1 PL/I parser cannot always resolve into procedures, so internal
  calls leak as cross-program edges and over-connect the graph (1 large cycle). The
  representative PL/I corpus (`zopeneditor-sample`, real IBM samples) parses cleanly.
  Fuller PL/I procedure resolution is a planned v2 enhancement.

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
