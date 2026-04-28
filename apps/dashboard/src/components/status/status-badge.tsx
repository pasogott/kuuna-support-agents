import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { RuntimeRunStatus, WorkflowStatus } from "@/lib/api-client/types";

type StatusBadgeStatus = WorkflowStatus | RuntimeRunStatus;

const STATUS_LABELS: Record<StatusBadgeStatus, string> = {
  draft: "Draft",
  ready: "Ready",
  published: "Published",
  archived: "Archived",
  active: "Active",
  inactive: "Inactive",
  provisioning: "Provisioning",
  failed: "Failed",
  queued: "Queued",
  processing: "Processing",
  running: "Running",
  started: "Started",
  succeeded: "Succeeded",
  cancelled: "Cancelled",
  timeout: "Timeout",
};

const STATUS_VARIANTS: Record<StatusBadgeStatus, BadgeProps["variant"]> = {
  draft: "violet",
  ready: "info",
  published: "success",
  active: "success",
  archived: "secondary",
  inactive: "secondary",
  provisioning: "warning",
  queued: "warning",
  processing: "warning",
  running: "warning",
  started: "warning",
  succeeded: "success",
  cancelled: "secondary",
  timeout: "destructive",
  failed: "destructive",
};

export function StatusBadge({ status }: { status: StatusBadgeStatus }) {
  return (
    <Badge variant={STATUS_VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
  );
}
