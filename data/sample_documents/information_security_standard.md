# Information Security Standard

## Severity levels

A severity-one incident is a confirmed event causing material loss of
confidentiality, integrity or service availability for multiple customers. The
incident commander records the start time, affected systems and remediation
status.

## Customer communication

Security owns the technical incident record. Legal reviews contractual
notification duties, and Account Owners coordinate customer communication using
the approved incident summary.

## Contract impact

An incident does not automatically change contract dates. Any termination or
commercial remedy must follow the contract and exception approval process.

## Severity-two incidents

A severity-two incident has material operational impact but does not meet the
multi-customer or material-loss threshold for severity one. The incident
commander may raise or lower severity as evidence changes. Reclassification is
timestamped and does not erase the earlier response record.

## Evidence handling

Logs, forensic images and investigation notes are stored in the restricted
incident workspace. Evidence exports include a checksum, collector identity
and collection time. Customer-facing summaries describe confirmed facts and
do not include credentials, unrelated customer data or speculative root
causes.

## Notification assessment

Legal records the jurisdictions, contractual clauses and decision deadline used
for the notification assessment. A technical alert is not automatically a
legal notification. Security supplies affected systems, data categories and
exposure timing so Legal can make the assessment.

## Access during response

Emergency access is time-limited, attributable and reviewed after the
incident. Responders use named accounts whenever technically possible. Shared
credentials created for recovery are rotated or removed before the incident is
closed.

## Recovery gates

The incident commander confirms containment, service restoration and monitoring
before moving an incident to recovery. Closure additionally requires an owner
for corrective actions and a scheduled review. Restoring service alone does
not close the investigation.

## Retention schedule

| Record | Minimum retention |
| --- | --- |
| Severity-one incident record | 7 years |
| Severity-two incident record | 3 years |
| Temporary responder access review | 1 year |
| Customer notification decision | 7 years |
