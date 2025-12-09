# Security with Pipenv

This guide covers security best practices when using Pipenv, including vulnerability scanning, hash verification, dependency management, and other security considerations.

## Security Features in Pipenv

Pipenv includes several built-in security features that help protect your projects from supply chain attacks and other security vulnerabilities.

### Hash Verification

Pipenv automatically generates cryptographic hashes for all packages in your `Pipfile.lock`. These hashes are verified during installation to ensure that the packages haven't been tampered with.

```json
{
    "requests": {
        "hashes": [
            "sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b",
            "sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e"
        ],
        "index": "pypi",
        "version": "==2.28.1"
    }
}
```

When you run `pipenv install`, Pipenv verifies that the downloaded packages match these hashes, protecting against:

- Man-in-the-middle attacks
- Compromised package repositories
- Malicious package substitution

### Vulnerability Scanning

Pipenv includes the [safety](https://github.com/pyupio/safety) package, which scans your dependencies for known security vulnerabilities.

```bash
$ pipenv check --scan
```

This command checks your dependencies against the PyUp Safety database of known vulnerabilities and alerts you to any issues.

Example output:

```
Scanning dependencies for security vulnerabilities...
Vulnerability found in django version 2.2.0
Vulnerability ID: 38449
Affected spec: <2.2.24
ADVISORY: Django 2.2.x before 2.2.24 allows QuerySet.order_by SQL injection if order_by is untrusted input.
CVE-2021-33203
For more information, please visit https://pyup.io/v/38449/742

Scan was completed. 1 vulnerability was found.
```

### Deterministic Builds

The `Pipfile.lock` ensures that everyone working on your project gets the exact same versions of all dependencies, including sub-dependencies. This prevents "works on my machine" problems and ensures consistent behavior across environments.

## Security Best Practices

### 1. Keep Dependencies Up to Date

Regularly update your dependencies to get the latest security fixes:

```bash
# Check for outdated packages
$ pipenv update --outdated

# Update all packages
$ pipenv update
```

For production systems, test updates thoroughly before deployment.

### 2. Use the `--deploy` Flag in Production

When installing dependencies in production environments, use the `--deploy` flag:

```bash
$ pipenv install --deploy
```

This ensures that your `Pipfile.lock` is up-to-date and fails if it isn't, preventing accidental use of outdated or insecure dependencies.

### 3. Regularly Scan for Vulnerabilities

Make vulnerability scanning a regular part of your development workflow:

```bash
$ pipenv check --scan
```

Consider integrating this into your CI/CD pipeline to catch vulnerabilities automatically.

### 4. Pin Dependencies Appropriately

For applications, pin dependencies to specific versions to ensure consistency and prevent unexpected updates:

```toml
[packages]
requests = "==2.28.1"
flask = "==2.0.1"
```

For libraries, use more flexible version constraints to allow compatibility with other packages:

```toml
[packages]
requests = ">=2.27.0,<3.0.0"
```

### 5. Commit Both Pipfile and Pipfile.lock

Always commit both `Pipfile` and `Pipfile.lock` to version control. The lock file contains the exact versions and hashes of all dependencies, ensuring consistent and secure builds.

### 6. Use Private Package Repositories Securely

When using private package repositories, ensure they're accessed securely:

```toml
[[source]]
name = "private"
url = "https://private-repo.example.com/simple"
verify_ssl = true
```

Use environment variables for credentials rather than hardcoding them:

```bash
$ export PIP_EXTRA_INDEX_URL=https://${USERNAME}:${PASSWORD}@private-repo.example.com/simple
```

### 7. Isolate Development and Production Dependencies

Keep development dependencies separate from production dependencies:

```bash
# Install a development dependency
$ pipenv install pytest --dev
```

In production, install only production dependencies:

```bash
$ pipenv install --deploy
```

## Vulnerability Management

### Understanding Vulnerability Reports

When `pipenv check --scan` identifies vulnerabilities, it provides information to help you assess the risk:

- **Vulnerability ID**: A unique identifier for the vulnerability
- **Affected spec**: The version range affected by the vulnerability
- **Advisory**: A description of the vulnerability
- **CVE**: The Common Vulnerabilities and Exposures identifier
- **More information**: A link to detailed information about the vulnerability

### Addressing Vulnerabilities

When vulnerabilities are found, you have several options:

1. **Update the affected package**:
   ```bash
   $ pipenv update vulnerable-package
   ```

2. **Pin to a non-vulnerable version**:
   ```toml
   [packages]
   vulnerable-package = "==2.0.1"  # A version without the vulnerability
   ```

3. **Ignore specific vulnerabilities** (use with caution):
   ```bash
   $ pipenv check --scan --ignore 38449
   ```

4. **Apply patches or workarounds** as recommended in the vulnerability advisory.

### Vulnerability Notification

For automated vulnerability notifications:

1. Set up [PyUp.io](https://pyup.io/) to monitor your dependencies.
2. Configure GitHub's Dependabot alerts if your code is hosted on GitHub.
3. Use a third-party security scanning service like Snyk or Sonatype.

## Supply Chain Security

### Understanding Supply Chain Attacks

Supply chain attacks target the dependencies your project relies on. These can include:

- Typosquatting attacks (malicious packages with names similar to popular packages)
- Dependency confusion attacks
- Compromised package maintainer accounts
- Malicious code inserted into legitimate packages

### Mitigating Supply Chain Risks

1. **Use hash verification**:
   Pipenv's hash verification in `Pipfile.lock` protects against many supply chain attacks.

2. **Audit new dependencies**:
   Before adding a new dependency, evaluate:
   - Is it actively maintained?
   - Does it have a good security track record?
   - How many dependencies does it bring in?
   - Is it widely used and reviewed by the community?

3. **Consider vendoring critical dependencies**:
   For mission-critical applications, consider vendoring (including the source code directly in your project) key dependencies.

4. **Use a private package index**:
   For high-security environments, maintain a private package index with vetted packages.

## Security in CI/CD Pipelines

### Secure Pipeline Configuration

In your CI/CD pipeline:

```yaml
# Example GitHub Actions workflow
name: Security Checks

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 0 * * 0'  # Weekly scan

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install pipenv
        run: pip install pipenv
      - name: Install dependencies
        run: pipenv install --dev
      - name: Verify Pipfile.lock
        run: pipenv verify
      - name: Security scan
        run: pipenv check --scan
```

### Preventing Lock File Tampering

To prevent tampering with your lock file:

1. Verify the lock file hash in CI/CD:
   ```bash
   $ pipenv verify
   ```

2. Use signed commits in your version control system.

3. Implement branch protection rules requiring code review before merging.

## Environment Variable Security

### Secure .env File Usage

Pipenv automatically loads environment variables from `.env` files. To use them securely:

1. **Never commit .env files to version control**:
   ```bash
   # .gitignore
   .env
   ```

2. **Provide a template**:
   ```bash
   # .env.example (safe to commit)
   DATABASE_URL=postgresql://user:password@localhost/dbname
   SECRET_KEY=your-secret-key-here
   ```

3. **Use different .env files for different environments**:
   ```bash
   $ PIPENV_DOTENV_LOCATION=.env.production pipenv shell
   ```

### Handling Sensitive Data

For sensitive data like API keys and passwords:

1. Use environment variables instead of hardcoding values.

2. Consider using a secrets management service like HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault.

3. For local development, use `.env` files but keep them out of version control.

## Docker Security

When using Pipenv with Docker:

### Secure Dockerfile

```dockerfile
FROM python:3.10-slim AS builder

WORKDIR /app

# Copy dependency files
COPY Pipfile Pipfile.lock ./

# Install pipenv and dependencies
RUN pip install --no-cache-dir pipenv && \
    pipenv install --deploy --system && \
    pip uninstall -y pipenv virtualenv-clone virtualenv

# Use a smaller base image for the final image
FROM python:3.10-slim

WORKDIR /app

# Copy only the installed packages from the builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Run as non-root user
RUN useradd -m appuser
USER appuser

# Run the application
CMD ["python", "app.py"]
```

### Docker Security Best Practices

1. Use multi-stage builds to reduce image size and attack surface.
2. Run containers as a non-root user.
3. Scan container images for vulnerabilities using tools like Trivy or Docker Scout.
4. Use the `--deploy` flag to ensure consistent dependencies.
5. Don't store secrets in Docker images.

## Advanced Security Topics

### Auditing Direct and Transitive Dependencies

View your complete dependency graph:

```bash
$ pipenv graph
```

This helps you understand all the packages your project depends on, including transitive dependencies (dependencies of your dependencies).

### Custom Security Policies

For organizations with specific security requirements:

1. Create a custom security policy that defines:
   - Approved and prohibited packages
   - Version pinning requirements
   - Vulnerability handling procedures

2. Implement custom checks in your CI/CD pipeline.

3. Consider using tools like `pip-audit` or `safety` with custom vulnerability databases.

### Air-Gapped Environments

For environments without internet access:

1. Download packages and their dependencies on a connected system:
   ```bash
   $ pipenv lock -r > requirements.txt
   $ pip download -r requirements.txt -d ./packages
   ```

2. Transfer the packages directory to the air-gapped environment.

3. Install from the local directory:
   ```bash
   $ pip install --no-index --find-links=./packages -r requirements.txt
   ```

## Security Incident Response

If you discover a security vulnerability in a package:

1. **Isolate**: Temporarily remove or isolate the affected component if possible.

2. **Report**: Report the vulnerability to the package maintainers through their preferred channel (often GitHub issues or a security email).

3. **Mitigate**: Apply temporary workarounds or patches as needed.

4. **Update**: Once a fix is available, update to the patched version.

5. **Document**: Document the incident and response for future reference.

## Conclusion

Pipenv provides powerful tools to help secure your Python projects, but security requires ongoing attention. By following these best practices, you can significantly reduce the risk of security vulnerabilities in your projects.

Remember that security is a continuous process, not a one-time task. Regularly update dependencies, scan for vulnerabilities, and stay informed about security best practices in the Python ecosystem.

For more information on Python security in general, refer to the [Python Security documentation](https://python-security.readthedocs.io/).
