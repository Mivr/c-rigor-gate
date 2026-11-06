"""Findings and gate results. Findings are deterministic; anything volatile goes in metadata."""

from dataclasses import dataclass

from rigor_lib import jsonio

SEVERITY_ERROR = "error"
SEVERITY_INFO = "info"
_SEVERITIES = (SEVERITY_ERROR, SEVERITY_INFO)


def finding(rule, severity=SEVERITY_ERROR, **fields):
    """One finding. `rule` names the check; extra fields must be plain JSON data."""
    if severity not in _SEVERITIES:
        raise ValueError("unknown severity: %r" % (severity,))
    item = dict(fields)
    item["rule"] = rule
    item["severity"] = severity
    return item


@dataclass(frozen=True)
class GateResult:
    gate: str
    findings: list
    metadata: dict

    @property
    def status(self):
        for item in self.findings:
            if item["severity"] == SEVERITY_ERROR:
                return "FAIL"
        return "PASS"

    def sorted_findings(self):
        return sorted(self.findings, key=jsonio.canonical_dumps)

    def findings_bytes(self):
        """Canonical bytes of the findings alone (what the verdict commits to)."""
        return jsonio.canonical_dumps(self.sorted_findings())

    def to_json_bytes(self):
        document = {
            "gate": self.gate,
            "status": self.status,
            "findings": self.sorted_findings(),
            "metadata": self.metadata,
        }
        return jsonio.canonical_dumps(document)
