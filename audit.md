# Security & Code Quality Audit Report

This report outlines the vulnerabilities, security misconfigurations, and code quality issues identified during the static analysis of the project's codebase (`backend` and `pipeline` components). All findings have been verified and ingested into the system `AuditLog`.

## Executive Summary

- **Critical**: 0
- **High**: 0
- **Medium**: 1
- **Low**: 6

---

## 🟡 Medium Severity

### 1. Insecure Temporary File Generation (CWE-377)
**Component:** `backend/app.py` (Lines 315, 321)
- **Description**: The application relies on `tempfile.mktemp()` when processing uploaded identity documents and live captures. This function is deprecated and inherently insecure, as it is vulnerable to race conditions (an attacker could create a symbolic link with the predicted filename before the application opens it, leading to arbitrary file overwrite or information disclosure).
- **Recommendation**: Replace `tempfile.mktemp` with `tempfile.NamedTemporaryFile` with `delete=False` and properly manage the file descriptors.

---

## 🟢 Low Severity / Code Quality

### 2. Potential Hardcoded JWT Secret (CWE-259)
**Component:** `backend/app.py` (Line 178)
- **Description**: A static fallback secret (`sih-hackathon-dev-secret-change-in-prod`) is baked into the code if `JWT_SECRET` is not provided in the environment. While currently gated by warnings and primarily intended for demo builds, leaving fallback secrets in code can lead to security breaches if deployed to production without configuration.
- **Recommendation**: Mandate `JWT_SECRET` at startup and raise an exception if it's missing in a non-development environment.

### 3. Hardcoded Credentials for Mock Users
**Component:** `backend/seed.py` (Lines 51-53)
- **Description**: Hardcoded passwords (e.g., `Officer@123`) are provided for the mock initialization of the database.
- **Recommendation**: These should ideally be generated securely or ingested via environment variables rather than hardcoded, even for seeding.

### 4. Insecure Pseudo-Random Generators (CWE-330)
**Component:** `pipeline/gemini_scanner.py`
- **Description**: The use of `random.choice` and `random.uniform` for cryptographic or security contexts is discouraged. While this is currently used to mock score generation during offline/simulated scanning, `secrets` module should be used if random generation handles sensitive flow logic.
- **Recommendation**: Swap `random` with the `secrets` module.

### 5. Broad Exception Suppression (CWE-703)
**Component:** `pipeline/liveness.py` (Line 177)
- **Description**: A blanket `except Exception: pass` suppresses all errors during `landmarker.close()`. This swallows `KeyboardInterrupt` and hides genuine operational faults.
- **Recommendation**: Catch explicit exceptions (like resource exhaustion or missing file descriptors) instead of standard exceptions.

### 6. Subprocess Invocation (CWE-78 context)
**Component:** `pipeline/ocr_mrz.py`
- **Description**: The file imports the `subprocess` module. Although its usage may be intended for backend tasks, any unsanitized user inputs passing into `subprocess.run()` pose a critical command-injection threat.
- **Recommendation**: Ensure that all inputs injected into the subprocess calls are stringently validated and parameterized.

### 7. Code Bloat: Unused Imports
**Component:** `pipeline/*`
- **Description**: Static analysis identified numerous unused imports (`insightface`, `cv2`, `typing.Any`) across `face_match.py`, `demographic.py`, and `tamper.py`.
- **Recommendation**: Prune unused dependencies to reduce startup overhead and minimize the runtime attack surface.
