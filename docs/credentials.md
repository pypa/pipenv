# Managing Credentials in Pipenv

This guide covers best practices for securely managing credentials and authentication in Pipenv, including environment variables, private repositories, and security considerations.

## Credentials in Package Sources

When working with private package repositories or authenticated services, you need to securely manage credentials in your Pipenv workflow.

### Environment Variable Expansion

Pipenv automatically expands environment variables in your `Pipfile`, providing a secure way to inject credentials without storing them in version control.

#### Basic Environment Variable Syntax

You can use environment variables in your `Pipfile` using the following syntax:

- `${VARIABLE_NAME}` - Standard syntax
- `$VARIABLE_NAME` - Alternative syntax
- `%VARIABLE_NAME%` - Windows-specific syntax (also supported on all platforms)

#### Example: Private Repository Authentication

```toml
[[source]]
url = "https://${USERNAME}:${PASSWORD}@mypypi.example.com/simple"
verify_ssl = true
name = "private-pypi"
```

When Pipenv reads this `Pipfile`, it will replace `${USERNAME}` and `${PASSWORD}` with the values of the corresponding environment variables.

#### Setting Environment Variables

Before running Pipenv commands, set the required environment variables:

**Linux/macOS:**
```bash
$ export USERNAME="your-username"
$ export PASSWORD="your-password"
$ pipenv install
```

**Windows (Command Prompt):**
```cmd
> set USERNAME=your-username
> set PASSWORD=your-password
> pipenv install
```

**Windows (PowerShell):**
```powershell
> $env:USERNAME="your-username"
> $env:PASSWORD="your-password"
> pipenv install
```

### Security Considerations

Pipenv hashes your `Pipfile` *before* expanding environment variables and substitutes them again when installing from the lock file. This means:

1. Your credentials are never stored in the lock file
2. You don't need to commit any secrets to version control
3. Different developers can use different credentials with the same `Pipfile`

```{warning}
While environment variables provide better security than hardcoded credentials, they are still accessible to any process running with the same user permissions. For highly sensitive credentials, consider using a dedicated secrets management solution.
```

### URL Encoding for Special Characters

If your credentials contain special characters, they must be URL-encoded according to [RFC 3986](https://datatracker.ietf.org/doc/html/rfc3986).

For example, if your password is `p@ssw0rd!`, it should be encoded as `p%40ssw0rd%21`:

```toml
[[source]]
url = "https://${USERNAME}:${PASSWORD_ENCODED}@mypypi.example.com/simple"
verify_ssl = true
name = "private-pypi"
```

You can generate URL-encoded strings using Python:

```python
import urllib.parse
print(urllib.parse.quote("p@ssw0rd!", safe=""))
# Output: p%40ssw0rd%21
```

## Credentials in Package Requirements

Environment variables can also be used in package requirement specifiers, but with some limitations.

### VCS Repository Authentication

For version control system (VCS) repositories that require authentication:

```toml
[packages]
requests = {git = "git://${USERNAME}:${PASSWORD}@private.git.com/psf/requests.git", ref = "2.22.0"}
```

```{note}
For VCS repositories, only the `${VAR_NAME}` syntax is supported. Neither `$VAR_NAME` nor `%VAR_NAME%` will work in this context.
```

### Runtime vs. Install-time Expansion

It's important to understand that environment variables are expanded at runtime, not when the `Pipfile` or `Pipfile.lock` is created. This means:

1. The entries in `Pipfile` and `Pipfile.lock` remain untouched
2. You need to have the environment variables set every time you run Pipenv commands
3. Different environments (development, CI/CD, production) can use different credentials

## Keyring Integration

Pipenv supports keyring integration for authentication to private registries. With pip 23.1+, there are two approaches to configure keyring authentication.

### Modern Approach: System-Wide Keyring (pip >= 23.1)

Starting with pip 23.1, you can install keyring system-wide (outside of your project virtualenv) and configure pip to use it via the subprocess provider. This is the recommended approach as it doesn't require installing keyring in every project.

#### Setup Steps

1. **Install keyring globally** (using pip, pipx, or your system package manager):
   ```bash
   # Using pip (user install)
   $ pip install --user keyring keyrings.google-artifactregistry-auth

   # Or using pipx (recommended for CLI tools)
   $ pipx install keyring
   $ pipx inject keyring keyrings.google-artifactregistry-auth
   ```

2. **Ensure keyring is on your PATH**:
   ```bash
   $ which keyring
   /home/user/.local/bin/keyring
   ```

3. **Ensure virtualenv seeds pip >= 23.1** (one-time setup):
   ```bash
   $ virtualenv --upgrade-embed-wheels
   ```

4. **Configure pip to use the subprocess keyring provider**:
   ```bash
   # Global configuration (recommended)
   $ pip config set --global keyring-provider subprocess

   # Or user-level configuration
   $ pip config set --user keyring-provider subprocess
   ```

5. **Configure your index URL with the appropriate username**:
   - For Google Artifact Registry: use `oauth2accesstoken` as username
   - For Azure Artifacts: use `VssSessionToken` as username

   ```toml
   # Pipfile
   [[source]]
   url = "https://oauth2accesstoken@europe-python.pkg.dev/my-project/python/simple/"
   verify_ssl = true
   name = "private-gcp"
   ```

### Legacy Approach: Keyring in Project Virtualenv

Alternatively, you can install keyring directly in your project's virtual environment. This approach works with all pip versions but requires installing keyring in every project.

### Google Cloud Artifact Registry

Google Cloud Artifact Registry supports authentication via keyring:

1. Install the required packages:
   ```bash
   $ pipenv run pip install keyring keyrings.google-artifactregistry-auth
   ```

2. Configure your `Pipfile`:
   ```toml
   [[source]]
   url = "https://pypi.org/simple"
   verify_ssl = true
   name = "pypi"

   [[source]]
   url = "https://europe-python.pkg.dev/my-project/python/simple"
   verify_ssl = true
   name = "private-gcp"

   [packages]
   flask = "*"
   private-test-package = {version = "*", index = "private-gcp"}
   ```

3. If the keyring might ask for user input, you may need to disable input enforcement:
   ```toml
   [pipenv]
   disable_pip_input = false
   ```

### Azure Artifact Registry

For Azure Artifact Registry:

1. Install the required packages:
   ```bash
   $ pipenv run pip install keyring artifacts-keyring
   ```

2. Configure your `Pipfile` similar to the Google Cloud example above, using `VssSessionToken` as the username in your index URL.

### AWS CodeArtifact

For AWS CodeArtifact:

1. Install the required packages:
   ```bash
   $ pipenv run pip install keyring keyrings.codeartifact
   ```

2. Configure your `Pipfile` with the appropriate AWS CodeArtifact URL.

## Best Practices for Credential Management

### Use Environment Variables

Always use environment variables instead of hardcoding credentials:

```toml
# Good
url = "https://${USERNAME}:${PASSWORD}@private-repo.example.com/simple"

# Bad
url = "https://actual-username:actual-password@private-repo.example.com/simple"
```

### Store Credentials in .env Files

For local development, store credentials in `.env` files that are not committed to version control:

```
# .env
USERNAME=your-username
PASSWORD=your-password
```

Add `.env` to your `.gitignore`:
```
# .gitignore
.env
```

Pipenv will automatically load variables from `.env` files when you run commands.

### Provide Templates

Include a template `.env.example` file in your repository:

```
# .env.example
USERNAME=
PASSWORD=
```

This helps other developers understand which environment variables they need to set.

### Use Different Credentials for Different Environments

Maintain separate credential sets for different environments:

```
# .env.development
USERNAME=dev-username
PASSWORD=dev-password

# .env.production
USERNAME=prod-username
PASSWORD=prod-password
```

Use them with:
```bash
$ PIPENV_DOTENV_LOCATION=.env.development pipenv install
```

### Rotate Credentials Regularly

Regularly rotate your credentials to minimize the impact of potential leaks:

1. Generate new credentials
2. Update your environment variables or `.env` files
3. Revoke the old credentials

### Consider Credential Managers

For team environments, consider using dedicated credential management solutions:

- [HashiCorp Vault](https://www.vaultproject.io/)
- [AWS Secrets Manager](https://aws.amazon.com/secrets-manager/)
- [Google Secret Manager](https://cloud.google.com/secret-manager)
- [Azure Key Vault](https://azure.microsoft.com/en-us/services/key-vault/)

These can be integrated into your workflow to provide secure, centralized credential management.

## CI/CD Integration

### GitHub Actions

For GitHub Actions, use secrets to store credentials:

```yaml
name: Python Package

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    - name: Install dependencies
      env:
        USERNAME: ${{ secrets.PYPI_USERNAME }}
        PASSWORD: ${{ secrets.PYPI_PASSWORD }}
      run: |
        pip install pipenv
        pipenv install --dev
```

### GitLab CI

For GitLab CI, use CI/CD variables:

```yaml
stages:
  - test

test:
  stage: test
  image: python:3.10
  variables:
    USERNAME: ${PYPI_USERNAME}
    PASSWORD: ${PYPI_PASSWORD}
  script:
    - pip install pipenv
    - pipenv install --dev
    - pipenv run pytest
```

### Jenkins

For Jenkins, use credentials binding:

```groovy
pipeline {
    agent {
        docker {
            image 'python:3.10'
        }
    }
    stages {
        stage('Build') {
            steps {
                withCredentials([
                    string(credentialsId: 'pypi-username', variable: 'USERNAME'),
                    string(credentialsId: 'pypi-password', variable: 'PASSWORD')
                ]) {
                    sh 'pip install pipenv'
                    sh 'pipenv install --dev'
                    sh 'pipenv run pytest'
                }
            }
        }
    }
}
```

## Troubleshooting

### Common Issues

#### Environment Variables Not Being Expanded

If environment variables aren't being expanded:

1. Verify the variables are set correctly:
   ```bash
   $ echo $USERNAME
   $ echo $PASSWORD
   ```

2. Check the syntax in your `Pipfile`:
   - Use `${VARIABLE_NAME}` for the most reliable expansion
   - Ensure there are no typos in variable names

3. Try setting the variables directly in the command:
   ```bash
   $ USERNAME=user PASSWORD=pass pipenv install
   ```

#### Authentication Failures

If you're experiencing authentication failures:

1. Verify your credentials work outside of Pipenv:
   ```bash
   $ curl -u "${USERNAME}:${PASSWORD}" https://private-repo.example.com/simple
   ```

2. Check for special characters that might need URL encoding

3. Ensure your credentials have the necessary permissions

#### Keychain Integration Issues

If keychain integration isn't working:

1. Verify the keychain packages are installed:
   ```bash
   $ pipenv run pip list | grep keyring
   ```

2. Check if the keychain is properly configured for your system

3. Try disabling pip input enforcement:
   ```toml
   [pipenv]
   disable_pip_input = false
   ```

## Security Considerations

### Credential Leakage Risks

Be aware of these common credential leakage risks:

1. **Command history**: Credentials passed directly in commands are stored in shell history
2. **Process listing**: Environment variables set on the command line may be visible in process listings
3. **Log files**: Debug logs might include expanded environment variables
4. **Core dumps**: Application crashes might include memory containing credentials

### Mitigating Risks

To mitigate these risks:

1. Use `.env` files instead of setting variables on the command line
2. Limit access to environments where credentials are used
3. Use temporary credentials or tokens when possible
4. Implement the principle of least privilege for all credentials
5. Monitor for unauthorized access to your repositories

## Conclusion

Properly managing credentials in Pipenv is essential for security and maintainability. By using environment variables, `.env` files, and following best practices, you can securely authenticate to private repositories and services without compromising sensitive information.

Remember that credential management is an ongoing process that requires regular review and updates to maintain security. Always follow the principle of least privilege and rotate credentials regularly to minimize potential security risks.
