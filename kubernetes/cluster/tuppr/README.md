Tuppr runs for the Sunday maintenance window. Two short CronJobs wake it at
03:55 and stop it at 06:15 in `Europe/Copenhagen`. The stop job requires both
upgrade plans to be `Completed` for their current generation. Pending, running,
failed, or unreadable plans leave the controller enabled for recovery and alerts.

Version changes made while the controller is off wait for the next scheduled
window. Admission webhook call failures are ignored while its endpoint is
offline; CRD schema validation still applies, and an available webhook still
rejects invalid plans. Helm installs and upgrades enable the controller so a chart update
cannot stop an active cluster upgrade. The scheduled stop job returns it to
zero after completion. Flux drift correction is disabled for this release so
ordinary reconciliation does not undo scheduled scaling.

For an unscheduled run, create a Job from `tuppr-wake` in `system-upgrade`. The
plans still honor their maintenance windows. Create a Job from `tuppr-sleep`
after completion to stop the controller. Job failure alerts cover failed runs,
and the operator availability alert applies only while replicas are
requested. Controller metrics are available while Tuppr runs; historical data
remains queryable while it is off.
