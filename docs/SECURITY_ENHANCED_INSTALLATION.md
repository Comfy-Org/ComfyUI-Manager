# Security-Enhanced URL Installation System

## Overview

Security constraints have been added to the `install_by_url` function to control URL-based installations according to the system's security level.

## Security Level and Risk Level Framework

### Security Levels (SecurityLevel)
- **strong**: Most restrictive, only trusted sources allowed
- **normal**: Standard security, most known platforms allowed
- **normal-**: Relaxed security, additional allowances for personal cloud environments
- **weak**: Most permissive security, for local development environments

### Risk Levels (RiskLevel)
- **block**: Complete block (always denied)
- **high+**: Very high risk (only allowed in local mode + weak/normal-)
- **high**: High risk (only allowed in local mode + weak/normal- or personal cloud + weak)
- **middle+**: Medium-high risk (weak/normal/normal- allowed in local/personal cloud)
- **middle**: Medium risk (weak/normal/normal- allowed in all environments)

## URL Risk Assessment Logic

### Low Risk (middle) - Trusted Platforms
```
- github.com
- gitlab.com
- bitbucket.org
- raw.githubusercontent.com
- gitlab.io
```

### High Risk (high+) - Suspicious/Local Hosting
```
- localhost, 127.0.0.1
- Private IP ranges: 192.168.*, 10.0.*, 172.*
- Temporary hosting: ngrok.io, herokuapp.com, repl.it, glitch.me
```

### Medium-High Risk (middle+) - Unknown Domains
```
- All domains not belonging to the above categories
```

### High Risk (high) - SSH Protocol
```
- URLs starting with ssh:// or git@
```

## Implemented Security Features

### 1. Security Validation (`_validate_url_security`)
```python
async def install_by_url(self, url: str, ...):
    # Security validation
    security_result = self._validate_url_security(url)
    if not security_result['allowed']:
        return self._report_failed_install_security(url, security_result['reason'], custom_name)
```

**Features**:
- Check current security level
- Assess URL risk
- Allow/block decision based on security policy

### 2. Failure Reporting (`_report_failed_install_security`)
```python
def _report_failed_install_security(self, url: str, reason: str, custom_name=None):
    # Security block logging
    print(f"[SECURITY] Blocked URL installation: {url}")

    # Record failed installation
    self._record_failed_install_nodepack({
        'type': 'url-security-block',
        'url': url,
        'package_name': pack_name,
        'reason': reason,
        'security_level': current_security_level,
        'timestamp': timestamp
    })
```

**Features**:
- Log blocked installation attempts to console
- Save failure information in structured format
- Return failure result as ManagedResult

### 3. Failed Installation Record Management (`_record_failed_install_nodepack`)
```python
def get_failed_install_reports(self) -> list:
    return getattr(self, '_failed_installs', [])
```

**Features**:
- Maintain recent 100 failure records
- Prevent memory overflow
- Provide API for monitoring and debugging

## Usage Examples

### Behavior by Security Setting

#### Strong Security Level
```python
# Most URLs are blocked
result = await manager.install_by_url("https://github.com/user/repo")
# Result: Blocked (github is also middle risk, so blocked at strong level)

result = await manager.install_by_url("https://suspicious-domain.com/repo.git")
# Result: Blocked (middle+ risk)
```

#### Normal Security Level
```python
# Trusted platforms allowed
result = await manager.install_by_url("https://github.com/user/repo")
# Result: Allowed

result = await manager.install_by_url("https://localhost/repo.git")
# Result: Blocked (high+ risk)
```

#### Weak Security Level (Local Development Environment)
```python
# Almost all URLs allowed
result = await manager.install_by_url("https://github.com/user/repo")
# Result: Allowed

result = await manager.install_by_url("https://192.168.1.100/repo.git")
# Result: Allowed (in local mode)

result = await manager.install_by_url("git@private-server.com:user/repo.git")
# Result: Allowed
```

### Failure Monitoring
```python
manager = UnifiedManager()

# Blocked installation attempt
await manager.install_by_url("https://malicious-site.com/evil-nodes.git")

# Check failure records
failed_reports = manager.get_failed_install_reports()
for report in failed_reports:
    print(f"Blocked: {report['url']} - {report['reason']}")
```

## Security Policy Matrix

| Risk Level | Strong | Normal | Normal- | Weak |
|------------|--------|--------|---------|------|
| **block**  | ❌ | ❌ | ❌ | ❌ |
| **high+**  | ❌ | ❌ | 🔒* | 🔒* |
| **high**   | ❌ | ❌ | 🔒*/☁️** | ✅ |
| **middle+**| ❌ | ❌ | 🔒*/☁️** | ✅ |
| **middle** | ❌ | ✅ | ✅ | ✅ |

- 🔒* : Allowed only in local mode
- ☁️** : Allowed only in personal cloud mode
- ✅ : Allowed
- ❌ : Blocked

## Error Message Examples

### Security Block
```
Installation blocked by security policy: URL installation blocked by security level: strong (risk: middle)
Target: awesome-nodes@url-blocked
```

### Console Log
```
[SECURITY] Blocked URL installation: https://suspicious-domain.com/repo.git
[SECURITY] Reason: URL installation blocked by security level: normal (risk: middle+)
[SECURITY] Package: repo
```

## Configuration Recommendations

### Production Environment
```json
{
  "security_level": "strong",
  "network_mode": "private"
}
```
- Most restrictive settings
- Only trusted sources allowed

### Development Environment
```json
{
  "security_level": "weak",
  "network_mode": "local"
}
```
- Permissive settings for development convenience
- Allow local repositories and development servers

### Personal Cloud Environment
```json
{
  "security_level": "normal-",
  "network_mode": "personal_cloud"
}
```
- Balanced settings for personal use
- Allow personal repository access

## Security Enhancement Benefits

### 1. Malware Prevention
- Automatic blocking from unknown sources
- Filter suspicious domains and IPs

### 2. Network Security
- Control private network access
- Restrict SSH protocol usage

### 3. Audit Trail
- Record all blocked attempts
- Log security events

### 4. Flexible Policy
- Customized security levels per environment
- Distinguish between production/development environments

## Backward Compatibility

- Existing `install_by_id` function unchanged
- No security validation applied to CNR-based installations
- `install_by_id_or_url` applies security only to URLs

This security enhancement significantly improves system security while maintaining the convenience of URL-based installations.
