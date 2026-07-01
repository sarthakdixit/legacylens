# Rule Pack Reference

Deterministic CWE/OWASP rules shipped in the `cwe` / `owasp` packs (both resolve to
the same combined set in v1). All are pattern/structure based and reproducible
(`source = rule`, authoritative). LLM-advisory findings are separate and always
flagged for human review.

Comment lines and string-literal contents are excluded, so commented-out code and
keywords inside messages never produce findings.

| ID | Title | CWE | OWASP | Severity | Languages |
|---|---|---|---|---|---|
| LL-SEC-001 | Hard-coded credential or secret | CWE-798 | A07:2021 | high | COBOL, PL/I |
| LL-SEC-002 | Hard-coded password in JCL | CWE-798 | A07:2021 | high | JCL |
| LL-SEC-003 | Possible SQL injection via dynamic SQL | CWE-89 | A03:2021 | high | COBOL |
| LL-SEC-004 | Sensitive data written to log/output | CWE-532 | A09:2021 | medium | COBOL |
| LL-SEC-005 | Dynamic program CALL / CICS transfer | CWE-94 | A03:2021 | medium (CALL) · low (CICS) | COBOL |
| LL-SEC-006 | Hard-coded IP address | CWE-1051 | — | low | any |
| LL-SEC-007 | Active debug code left in source (READY TRACE / EXHIBIT) | CWE-489 | — | low | COBOL |
| LL-SEC-008 | EVALUATE without WHEN OTHER (missing default case) | CWE-478 | — | medium | COBOL |
| LL-SEC-009 | Sensitive data written to output (PUT LIST/EDIT) | CWE-532 | A09:2021 | medium | PL/I |

Notes:

- **LL-SEC-005** rates a dynamic COBOL `CALL` as *medium*, but a dynamic
  `EXEC CICS LINK/XCTL PROGRAM(var)` as *low* — the latter is the ubiquitous CICS
  pattern and usually benign, so it is informational rather than an alarm.
- Severities and mappings are advisory defaults; clients can layer custom packs
  (planned) and use suppressions/baseline to tune what gates CI.

See [VALIDATION.md](VALIDATION.md) for how these behave on real public repositories.

## Custom rule packs

Add detection rules without writing Python. Point `analysis.compliance.pack_paths`
at YAML files and list the pack's `name` in `rule_packs`:

```yaml
# rules/acme.yaml
name: acme
rules:
  - id: ACME-001
    title: Hard-coded internal hostname
    severity: medium            # info|low|medium|high|critical
    cwe: CWE-1051               # optional
    owasp: null                 # optional
    languages: [cobol, jcl]     # omit = all languages
    pattern: "acme-corp\\.internal"   # regex, matched per code line
    rationale: "..."
    remediation: "..."
    confidence: 0.8
```

```yaml
analysis:
  compliance:
    rule_packs: [cwe, owasp, acme]
    pack_paths: [rules/acme.yaml]
```

Comments are skipped; unlike the built-ins, custom rules match the raw line (so they
can target string-literal contents such as hostnames or dataset names).

## Regulatory compliance frameworks

A framework maps a CWE to control references, enriching each finding with the
controls it implicates (no new detection rules needed). Built-in: `pci-dss`,
`nist-800-53` (indicative mappings). Add your own:

```yaml
# frameworks/acme-policy.yaml
name: ACME-POLICY
title: ACME Secure Coding Policy v1
map:
  CWE-798: ["SEC-1.1", "SEC-1.2"]
  CWE-89:  ["SEC-3.4"]
```

```yaml
analysis:
  compliance:
    frameworks: [pci-dss, nist-800-53]
    framework_paths: [frameworks/acme-policy.yaml]
```

Findings then carry `controls` (e.g. `PCI-DSS:8.6.2`) in JSON, SARIF, and HTML.
`legacylens compliance` summarizes findings grouped by control.

> Built-in control mappings are **indicative** starting points; confirm against the
> current version of each standard for a formal audit.
