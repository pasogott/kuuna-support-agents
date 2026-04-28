import Link from "next/link";
import { notFound } from "next/navigation";

import { StatusBadge } from "@/components/status/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { getRuntimeRun } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils/format";

type Params = Promise<{ runId: string }>;

function MonoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-muted-foreground">{label}</span>
      <code className="rounded-sm border border-border bg-muted px-2 py-0.5 font-mono text-xs text-foreground">
        {value}
      </code>
    </div>
  );
}

export default async function RuntimeRunDetailPage({ params }: { params: Params }) {
  const { runId } = await params;
  const run = await getRuntimeRun(runId);

  if (!run) {
    notFound();
  }

  const execJson = JSON.stringify(run.execution ?? {}, null, 2);

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Runtime run"
        description="Detailed execution record for one container run."
        actions={
          run.providerGroupId ? (
            <Link
              href={`/audit/runs?providerGroupId=${encodeURIComponent(run.providerGroupId)}`}
              className="text-sm text-primary hover:underline"
            >
              View group runs
            </Link>
          ) : null
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
            <CardDescription>Identity + selection context.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pb-6">
            <MonoRow label="Run ID" value={run.id} />
            <MonoRow label="Group" value={run.providerGroupId} />
            <MonoRow label="Binding" value={run.bindingId} />
            <MonoRow label="Template version" value={run.templateVersionId} />
            <MonoRow label="Template build" value={run.templateBuildId ?? "n/a"} />
            <MonoRow label="Message" value={run.messageId ?? "n/a"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
            <CardDescription>Outcome and timing.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pb-6">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Status</span>
              <StatusBadge status={run.status} />
            </div>
            <MonoRow label="Started" value={formatDateTime(run.startedAt)} />
            <MonoRow label="Finished" value={run.finishedAt ? formatDateTime(run.finishedAt) : "n/a"} />
            <MonoRow label="Duration" value={typeof run.durationMs === "number" ? `${run.durationMs}ms` : "n/a"} />
            <MonoRow label="Image ref" value={run.imageRef} />
            <MonoRow label="Error" value={run.error ?? "n/a"} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Execution</CardTitle>
          <CardDescription>
            Raw execution metadata (tails, container name, limits). Kept small on purpose.
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-6">
          <pre className="max-h-[520px] overflow-auto rounded-md border border-border bg-muted p-4 text-xs">
            {execJson}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

