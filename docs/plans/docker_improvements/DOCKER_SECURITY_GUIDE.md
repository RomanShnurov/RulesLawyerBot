# Docker Security Guide for RulesLawyerBot

This guide provides detailed security recommendations for deploying RulesLawyerBot in Docker environments.

## Table of Contents

1. [Secret Management](#secret-management)
2. [Image Security](#image-security)
3. [Container Runtime Security](#container-runtime-security)
4. [Network Security](#network-security)
5. [Compliance & Scanning](#compliance--scanning)
6. [CI/CD Security](#cicd-security)

---

## Secret Management

### Problem: API Keys and Tokens in Environment Variables

Current approach exposes secrets to:
- `docker inspect` output
- Container logs and error messages
- Bash history
- Process listings

### Solution 1: Docker Secrets (Swarm Mode)

For Docker Swarm deployments:

```yaml
# docker-compose.yml
services:
  app:
    environment:
      TELEGRAM_TOKEN_FILE: /run/secrets/telegram_token
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
    secrets:
      - telegram_token
      - openai_key

secrets:
  telegram_token:
    file: ./secrets/telegram_token.txt
  openai_key:
    file: ./secrets/openai_key.txt
```

Update application code:

```python
# src/config.py
import os
from pathlib import Path

def load_secret(env_var: str, file_suffix: str = "_FILE") -> str:
    """
    Load secret from environment variable or file.

    Supports both direct env vars and file-based secrets:
    - If ENV_VAR_FILE is set, read from that file
    - Otherwise, read from ENV_VAR
    - Return empty string if neither exists
    """
    file_path = os.getenv(f"{env_var}{file_suffix}")

    if file_path and Path(file_path).exists():
        try:
            with open(file_path, 'r') as f:
                return f.read().strip()
        except IOError as e:
            raise ValueError(f"Cannot read secret from {file_path}: {e}")

    value = os.getenv(env_var)
    if not value:
        raise ValueError(f"Neither {env_var} nor {env_var}{file_suffix} is set")

    return value

# Usage
TELEGRAM_TOKEN = load_secret("TELEGRAM_TOKEN")
OPENAI_API_KEY = load_secret("OPENAI_API_KEY")
```

### Solution 2: External Secrets Operator (Kubernetes)

For Kubernetes deployments:

```yaml
# kubernetes/secretstore.yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: bot-secrets
spec:
  provider:
    vault:
      server: "https://vault.example.com:8200"
      path: "secret/data/ruleslawyerbot"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "ruleslawyerbot"

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: bot-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: bot-secrets
    kind: SecretStore
  target:
    name: bot-secrets
    creationPolicy: Owner
  data:
  - secretKey: telegram-token
    remoteRef:
      key: telegram_token
  - secretKey: openai-key
    remoteRef:
      key: openai_api_key
```

### Solution 3: AWS Secrets Manager

For AWS deployments:

```bash
# Store secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name ruleslawyerbot/telegram-token \
  --secret-string "your-token-here"

aws secretsmanager create-secret \
  --name ruleslawyerbot/openai-api-key \
  --secret-string "your-key-here"
```

Update docker-compose or ECS task definition:

```python
# src/aws_secrets.py
import boto3
import json
from functools import lru_cache

secrets_client = boto3.client('secretsmanager')

@lru_cache(maxsize=10)
def get_secret(secret_name: str) -> str:
    """Retrieve secret from AWS Secrets Manager."""
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        if 'SecretString' in response:
            return response['SecretString']
        else:
            return response['SecretBinary']
    except Exception as e:
        raise ValueError(f"Failed to retrieve secret {secret_name}: {e}")

# Usage
TELEGRAM_TOKEN = get_secret("ruleslawyerbot/telegram-token")
OPENAI_API_KEY = get_secret("ruleslawyerbot/openai-api-key")
```

### Best Practices for Secrets

1. **Never commit secrets** to version control
2. **Use .gitignore** to exclude `.env` files
3. **Rotate secrets regularly** (quarterly minimum)
4. **Audit secret access** in logs
5. **Use different secrets** for different environments
6. **Limit secret scope** to only what containers need
7. **Encrypt secrets in transit** (use HTTPS/TLS)

---

## Image Security

### 1. Pin Base Image Digests

Always use specific versions with SHA256 digests:

```dockerfile
# INSECURE - uses mutable tag
FROM python:3.11-slim

# SECURE - uses immutable digest
FROM python:3.11-slim@sha256:abc123def456...
```

Find digests:

```bash
# Using docker manifest
docker manifest inspect python:3.11-slim | grep digest

# Using registry API
curl -s https://registry.hub.docker.com/v2/library/python/manifests/3.11-slim \
  | jq '.config.digest'
```

### 2. Scan Base Images for Vulnerabilities

```bash
# Using Trivy
trivy image python:3.11-slim

# Using Snyk
snyk test --docker python:3.11-slim

# Using Grype
grype python:3.11-slim
```

### 3. Use Minimal Base Images

Comparison:

```
python:3.11                  898MB   (full installation)
python:3.11-slim             125MB   (reduced packages)
python:3.11-alpine           49MB    (minimal - may lack tools)
distroless python:3.11       60MB    (no shell, very minimal)
```

For RulesLawyerBot, `python:3.11-slim` is appropriate because it needs:
- `pip` for dependency installation
- Shell tools (unlikely but possible)
- Standard development tools

### 4. Build Multi-Stage with Minimal Runtime

```dockerfile
# Stage 1: Build
FROM python:3.11-slim AS builder

RUN pip install uv && \
    mkdir /build && \
    cd /build

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2: Runtime (minimal)
FROM python:3.11-slim

# Only copy what's needed
COPY --from=builder /build/.venv /app/.venv

# Copy only application code
COPY src/ ./src/

# Set PATH for venv
ENV PATH="/app/.venv/bin:$PATH"

# Non-root user
USER 1000:1000

CMD ["python", "-m", "src.main"]
```

### 5. Generate SBOM (Software Bill of Materials)

```bash
# Using syft
syft ruleslawyerbot:latest -o json > sbom.json
syft ruleslawyerbot:latest -o cyclonedx > sbom.xml

# Using grype with SBOM
grype sbom:sbom.json
```

In Dockerfile:

```dockerfile
# Add labels for SBOM reference
LABEL org.opencontainers.image.documentation="https://github.com/your-org/ruleslawyerbot"
LABEL org.opencontainers.image.source="https://github.com/your-org/ruleslawyerbot"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.vendor="Your Organization"
LABEL org.opencontainers.image.licenses="MIT"
```

---

## Container Runtime Security

### 1. Non-Root User (Already Implemented)

```dockerfile
# Create user with no shell
RUN useradd -m -u 1000 -s /sbin/nologin botuser

# Switch to user
USER botuser
```

Verify at runtime:

```bash
docker run ruleslawyerbot id
# uid=1000(botuser) gid=1000(botuser) groups=1000(botuser)
```

### 2. Drop Unnecessary Capabilities

```dockerfile
# Drop all capabilities then add back only needed ones
RUN setcap -r /usr/bin/python3 || true

# Or in docker-compose
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE  # Only if needed
```

### 3. Read-Only Filesystem

Make filesystem read-only except for specific volumes:

```yaml
# docker-compose.yml
services:
  app:
    read_only: true
    tmpfs:
      - /tmp:noexec,nodev,nosuid,size=100m
      - /run:noexec,nodev,nosuid,size=100m
    volumes:
      - ./rules_pdfs:/app/rules_pdfs:ro  # Read-only
      - ./data:/app/data:rw               # Read-write
```

### 4. Seccomp Profile

Restrict system calls:

```json
# seccomp.json - minimal profile
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "defaultErrnoRet": 1,
  "archMap": [
    {
      "architecture": "SCMP_ARCH_X86_64",
      "subArchitectures": ["SCMP_ARCH_X86", "SCMP_ARCH_X32"]
    }
  ],
  "syscalls": [
    {
      "names": [
        "accept4", "arch_prctl", "bind", "brk", "clone", "close",
        "connect", "dup", "dup2", "dup3", "epoll_create1", "epoll_ctl",
        "epoll_wait", "exit", "exit_group", "fcntl", "fstat", "fstatfs",
        "futex", "getcwd", "getegid", "getgid", "getpid", "getrandom",
        "getrlimit", "getuid", "ioctl", "listen", "lseek", "madvise",
        "mmap", "mprotect", "mremap", "munmap", "open", "openat",
        "pipe", "pipe2", "poll", "prctl", "pread64", "prlimit64",
        "pwrite64", "read", "readlink", "readlinkat", "readv", "recvfrom",
        "recvmmsg", "recvmsg", "restart_syscall", "rseq", "rt_sigaction",
        "rt_sigpending", "rt_sigprocmask", "rt_sigreturn", "rt_sigsuspend",
        "sched_getaffinity", "sched_setaffinity", "select", "sendfile",
        "sendmmsg", "sendmsg", "sendto", "set_robust_list", "set_tid_address",
        "setgroups", "sethostname", "setitimer", "setpgid", "setpgrp",
        "setpriority", "setregid", "setresgid", "setresuid", "setreuid",
        "setrlimit", "setsid", "setsockopt", "settimeofday", "setuid",
        "shutdown", "sigaction", "sigaltstack", "signal", "signalfd",
        "signalfd4", "sigpending", "sigprocmask", "sigsuspend", "socket",
        "socketpair", "stat", "statfs", "statx", "sigreturn", "splice",
        "statx", "symlink", "symlinkat", "sync", "sysinfo", "syslog",
        "tgkill", "time", "timerfd_create", "timerfd_gettime",
        "timerfd_settime", "times", "tkill", "truncate", "umask",
        "umount2", "uname", "unlink", "unlinkat", "unshare", "userfaultfd",
        "utime", "utimensat", "utimes", "vfork", "vhangup", "vmsplice",
        "wait4", "waitid", "waitpid", "write", "writev"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

Apply in docker-compose:

```yaml
services:
  app:
    security_opt:
      - seccomp=seccomp.json
```

### 5. AppArmor Profile

For Linux systems with AppArmor:

```
#include <tunables/global>

profile ruleslawyerbot flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  #include <abstractions/nameservice>

  /app/** r,
  /app/rules_pdfs/** rw,
  /app/data/** rw,

  /proc/*/stat r,
  /proc/*/status r,
  /proc/*/cmdline r,

  /usr/local/lib/python3.11/** mr,
  /usr/lib/python3.11/** mr,

  capability net_bind_service,
  capability sys_ptrace,

  deny /etc/shadow r,
  deny /etc/gshadow r,
  deny /root/** rwk,
}
```

Apply:

```bash
sudo apparmor_parser -r ruleslawyerbot.profile
docker run --security-opt apparmor=ruleslawyerbot ...
```

---

## Network Security

### 1. Network Isolation

```yaml
# docker-compose.yml
networks:
  bot-network:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: br-bot
    ipam:
      config:
        - subnet: 172.20.0.0/16

services:
  app:
    networks:
      - bot-network
    # No published ports - this is a backend service
```

### 2. Restrict Outbound Connections

If Telegram and OpenAI APIs are the only outbound connections needed:

```dockerfile
# Use iptables or firewall rules
RUN apt-get install -y iptables && \
    # Allow only outbound to Telegram and OpenAI
    iptables -A OUTPUT -d api.telegram.org -j ACCEPT && \
    iptables -A OUTPUT -d api.openai.com -j ACCEPT && \
    iptables -A OUTPUT -d api.proxyapi.ru -j ACCEPT && \
    iptables -A OUTPUT -j DROP
```

Better approach: Use network policies in Kubernetes:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: bot-network-policy
spec:
  podSelector:
    matchLabels:
      app: ruleslawyerbot
  policyTypes:
    - Egress
  egress:
    # Allow DNS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
    # Allow Telegram API
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 443
    # Allow OpenAI API
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 443
```

### 3. TLS/SSL for External Connections

In application code:

```python
# src/tls_config.py
import ssl
import certifi

def get_ssl_context():
    """Get secure SSL context for API calls."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context

# Use with OpenAI client
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    http_client=httpx.AsyncClient(
        verify=get_ssl_context()
    )
)
```

---

## Compliance & Scanning

### 1. Automated Image Scanning

GitHub Actions workflow:

```yaml
# .github/workflows/docker-security.yml
name: Docker Security Scan

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  schedule:
    - cron: '0 2 * * *'  # Daily 2 AM

jobs:
  scan:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Build Docker image
      run: |
        docker build -t ruleslawyerbot:${{ github.sha }} .

    - name: Run Trivy vulnerability scanner
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: ruleslawyerbot:${{ github.sha }}
        format: 'sarif'
        output: 'trivy-results.sarif'
        severity: 'HIGH,CRITICAL'

    - name: Upload Trivy results to GitHub Security tab
      uses: github/codeql-action/upload-sarif@v2
      if: always()
      with:
        sarif_file: 'trivy-results.sarif'

    - name: Run Snyk scan
      uses: snyk/actions/docker@master
      env:
        SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
      with:
        image: ruleslawyerbot:${{ github.sha }}
        args: --severity-threshold=high

    - name: Run Grype scan
      uses: anchore/scan-action@v3
      with:
        image: ruleslawyerbot:${{ github.sha }}
        fail-build: true
        severity-cutoff: high

    - name: Upload Grype SBOM
      uses: github/codeql-action/upload-sarif@v2
      with:
        sarif_file: ${{ steps.scan.outputs.sarif }}
```

### 2. Runtime Security Scanning

Using Falco for runtime security:

```yaml
# kubernetes/falco-values.yaml
falco:
  enabled: true
  grpc:
    enabled: true
  image:
    repository: falcosecurity/falco
    tag: latest

serviceAccount:
  create: true
  name: falco

rbac:
  create: true

podSecurityPolicy:
  create: false  # Deprecated
```

---

## CI/CD Security

### 1. Signed Container Images

Using Cosign:

```bash
# Generate signing keys
cosign generate-key-pair

# Sign image after build
cosign sign --key cosign.key ruleslawyerbot:latest

# Verify signature
cosign verify --key cosign.pub ruleslawyerbot:latest
```

In GitHub Actions:

```yaml
- name: Sign image with Cosign
  env:
    COSIGN_EXPERIMENTAL: 1
  run: |
    cosign sign ghcr.io/${{ github.repository }}:${{ github.sha }}
```

### 2. Supply Chain Security (SLSA)

Implement SLSA framework:

```yaml
# .github/workflows/slsa-build.yml
name: SLSA Build

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image: ${{ steps.meta.outputs.image }}
      digest: ${{ steps.build.outputs.digest }}

    steps:
    - uses: actions/checkout@v3

    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v2

    - name: Build and push
      id: build
      uses: docker/build-push-action@v4
      with:
        context: .
        push: true
        tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
        cache-from: type=gha
        cache-to: type=gha,mode=max
        provenance: true
        sbom: true

  provenance:
    needs: build
    uses: slsa-framework/slsa-github-generator/.github/workflows/generator_container_slsa3.yml@v1.4.0
    with:
      image: ${{ needs.build.outputs.image }}
      digest: ${{ needs.build.outputs.digest }}
      registry-username: ${{ github.actor }}
    secrets:
      registry-password: ${{ secrets.GITHUB_TOKEN }}
```

### 3. Dependency Scanning

```bash
# Use Safety to check Python dependencies
safety check --json > dependency-report.json

# Use pip-audit
pip-audit

# Use Dependabot (GitHub native)
# Enable in repository settings
```

---

## Security Checklist

- [ ] Secrets stored in secret management system
- [ ] Base image digests pinned with SHA256
- [ ] Non-root user in Dockerfile
- [ ] Unnecessary capabilities dropped
- [ ] Health checks implemented
- [ ] Logging configured without secrets
- [ ] Container image scanned for vulnerabilities
- [ ] SBOM generated and stored
- [ ] Network policies defined (Kubernetes)
- [ ] Read-only filesystem where possible
- [ ] Startup validation implemented
- [ ] Graceful shutdown handlers in place
- [ ] API calls use TLS 1.2+
- [ ] Automated scanning in CI/CD
- [ ] Container images signed
- [ ] Security policy documented

---

## References

- [CIS Docker Benchmark](https://www.cisecurity.org/cis-benchmarks/)
- [OWASP Container Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Container_Security_Cheat_Sheet.html)
- [Kubernetes Security Documentation](https://kubernetes.io/docs/concepts/security/)
- [SLSA Framework](https://slsa.dev/)
- [NIST Container Security Guide](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-190.pdf)
