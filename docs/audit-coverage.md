MON-241 | Monitoring audit coverage
Date: 2026-09-14
Owner: Mira Ellison, monitoring-platform

The nightly monitoring audit runs in the central operations service.
Snapshot selection in cotmon/store.py (SELECT_SNAPSHOTS) is covered
by this job. Coverage here means checking that selected snapshots
retain the complete episode history.

This note records the current coverage status for maintenance planning.
