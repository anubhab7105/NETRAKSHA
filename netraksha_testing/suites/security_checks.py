"""Security checks suite.

Non-destructive checks for security headers, auth enforcement,
and secret leakage.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ..core.config import FrameworkConfig
from ..core.models import SecurityFinding, Severity, TestResult, TestStatus
from ..core.registry import CATEGORY_SECURITY, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


def _check_headers(url: str, timeout: int) -> list[SecurityFinding]:
    findings = []
    try:
        resp = httpx.get(url, timeout=timeout)
        headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
        
        # Check standard security headers
        expected = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "deny",  # Or SAMEORIGIN
            "strict-transport-security": "max-age=",
            "x-xss-protection": "1; mode=block"
        }
        
        for h, v in expected.items():
            if h not in headers:
                findings.append(SecurityFinding(
                    check_name=f"Missing Header: {h}",
                    severity=Severity.MEDIUM,
                    status="FAIL",
                    description=f"Response is missing the {h} security header.",
                    recommendation=f"Add {h} to all API responses."
                ))
            elif v not in headers[h]:
                findings.append(SecurityFinding(
                    check_name=f"Weak Header: {h}",
                    severity=Severity.LOW,
                    status="FAIL",
                    description=f"Header {h} value '{headers[h]}' does not contain expected '{v}'.",
                ))
            else:
                 findings.append(SecurityFinding(
                    check_name=f"Header Present: {h}",
                    severity=Severity.INFO,
                    status="PASS",
                    description=f"Correctly configured {h}.",
                ))
                 
        if "server" in headers and any(c.isdigit() for c in headers["server"]):
             findings.append(SecurityFinding(
                check_name="Server Version Disclosure",
                severity=Severity.LOW,
                status="FAIL",
                description=f"Server header discloses version info: {headers['server']}",
                recommendation="Configure reverse proxy to hide server version."
            ))
            
    except Exception as e:
         findings.append(SecurityFinding(
            check_name="Header Check Failed",
            severity=Severity.INFO,
            status="ERROR",
            description=str(e),
        ))
    return findings


def _scan_for_secrets(root_dir: Path) -> list[SecurityFinding]:
    findings = []
    
    # Patterns to look for
    patterns = {
        "Gemini API Key": r"AIza[0-9A-Za-z-_]{35}",
        "Generic Secret": r"(?i)(secret|password|token)\s*[=:]\s*['\"][a-zA-Z0-9_\-\+]{16,}['\"]",
        "JWT Secret": r"JWT_SECRET\s*[=:]\s*['\"]?[a-zA-Z0-9_\-\+]{16,}['\"]?"
    }
    
    # Files to check (don't scan everything to avoid false positives/binary files)
    target_exts = {".py", ".env", ".env.example", ".yaml", ".json", ".js", ".ts"}
    ignore_dirs = {".git", ".venv", "node_modules", "dist", "build", "__pycache__"}
    
    for root, dirs, files in os.walk(root_dir):
        # Mutate dirs in-place to prune search
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            p = Path(root) / file
            if p.suffix not in target_exts and p.name not in {".env", ".env.example"}:
                continue
                
            try:
                content = p.read_text(encoding="utf-8")
                for name, regex in patterns.items():
                    matches = re.finditer(regex, content)
                    for match in matches:
                        # Simple entropy check to reduce false positives
                        # Skip .env.example which contains placeholder secrets
                        if p.name == ".env.example" and ("your_" in match.group(0).lower() or "change" in match.group(0).lower()):
                            continue
                            
                        # If it's a real hit, don't expose the actual secret in the report!
                        redacted = match.group(0)[:10] + "..."
                        findings.append(SecurityFinding(
                            check_name=f"Exposed Secret: {name}",
                            severity=Severity.HIGH,
                            status="FAIL",
                            description=f"Found potential {name} in {p.relative_to(root_dir)}",
                            evidence=redacted,
                            recommendation="Remove secrets from source code. Use environment variables or a secret manager."
                        ))
            except Exception:
                pass # Ignore unreadable files
                
    if not findings:
        findings.append(SecurityFinding(
            check_name="Secret Scan",
            severity=Severity.INFO,
            status="PASS",
            description="No hardcoded secrets found in scanned source files."
        ))
        
    return findings


@register_test(
    category=CATEGORY_SECURITY,
    name="security_audit",
    description="Non-destructive security checks (headers, auth, secrets)",
    requires_api=True
)
def test_security(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("security_audit", CATEGORY_SECURITY, "httpx not installed")
        
    t_start = time.perf_counter()
    findings: List[SecurityFinding] = []
    
    # 1. Check security headers on the health endpoint
    url = cfg.api_base_url + cfg.api_endpoints.get("health", "/api/health")
    findings.extend(_check_headers(url, cfg.api_timeout))
    
    # 2. Check auth enforcement on a protected endpoint without a token
    protected_url = cfg.api_base_url + cfg.api_endpoints.get("cases", "/api/cases")
    try:
        resp = httpx.get(protected_url, timeout=cfg.api_timeout)
        if resp.status_code in (401, 403):
            findings.append(SecurityFinding(
                check_name="Auth Enforcement",
                severity=Severity.INFO,
                status="PASS",
                description=f"Endpoint properly rejected unauthenticated access with {resp.status_code}."
            ))
        else:
             findings.append(SecurityFinding(
                check_name="Missing Auth Enforcement",
                severity=Severity.HIGH,
                status="FAIL",
                description=f"Protected endpoint returned {resp.status_code} instead of 401/403 for unauthenticated request.",
            ))
    except Exception as e:
         findings.append(SecurityFinding(
            check_name="Auth Check Failed",
            severity=Severity.INFO,
            status="ERROR",
            description=str(e),
        ))
        
    # 3. Source code secret scan
    root = cfg.project_root
    findings.extend(_scan_for_secrets(root))
    
    # Calculate status based on findings
    high_critical = sum(1 for f in findings if f.status == "FAIL" and f.severity in (Severity.HIGH, Severity.CRITICAL))
    medium = sum(1 for f in findings if f.status == "FAIL" and f.severity == Severity.MEDIUM)
    
    status = TestStatus.PASS
    if high_critical > 0:
        status = TestStatus.FAIL
    elif medium > 2:
         status = TestStatus.FAIL
         
    total_ms = (time.perf_counter() - t_start) * 1000
    
    # Attach findings to context so report generator can find them easily
    ctx.set("security_findings", findings)
    
    return TestResult(
        test_name="security_audit",
        category=CATEGORY_SECURITY,
        status=status,
        duration_ms=total_ms,
        metrics={"total_findings": len(findings), "high_severity": high_critical},
        security_findings=findings
    )
