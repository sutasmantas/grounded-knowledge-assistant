# Security

This repository is a portfolio application with tested tenant and document ACL
enforcement. It is not a production authentication boundary. Do not index
confidential documents in a public deployment.

## Reporting a vulnerability

Please open a private GitHub security advisory for the repository owner instead
of publishing exploit details in an issue.

## Data handling

- uploaded files are read from a temporary directory and deleted after indexing
- extracted passages and vectors remain in `data/runtime`
- OpenAI-compatible mode sends the question and retrieved passages to the
  configured model endpoint
- `.env` and `data/runtime` are excluded from Git
- tenant and ACL payload filters are applied before vector ranking
- metadata, versions, hashes, jobs, and idempotency keys are tenant-scoped;
  destructive actions and job controls are owner-only
- questions and retrieved passages are not written to structured request logs
  or OpenTelemetry span attributes
- high-confidence embedded instructions are flagged and quarantined from model
  context; remote-resource output markup is rejected

The `X-Atlas-*` identity headers are a trusted-gateway demo adapter. A production
deployment must replace or protect them with validated OIDC/JWT claims or
gateway-signed identity; never accept caller-selected tenant identity from the
public internet. Encryption at rest, malware scanning, rate limits, audit-log
export, and deployment-specific authorization administration are also required
before production use.

The deterministic prompt-injection controls cover known patterns and reduce
obvious indirect-injection paths. They do not make a probabilistic model
generally injection-proof. Provider-backed releases need threat-model-specific
red-team testing and review; see [docs/observability.md](docs/observability.md).
