import Link from "next/link";

import { SimpleTable } from "@/components/data-table/simple-table";
import { StatusBadge } from "@/components/status/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Notice } from "@/components/ui/notice";
import { PageHeader } from "@/components/ui/page-header";
import { listRuntimeRuns } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils/format";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function getSingleParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function RuntimeRunsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const providerGroupId = getSingleParam(params.providerGroupId);
  const messageId = getSingleParam(params.messageId);
  const bindingId = getSingleParam(params.bindingId);
  const templateVersionId = getSingleParam(params.templateVersionId);

  const runs = await listRuntimeRuns({
    providerGroupId: providerGroupId ?? undefined,
    messageId: messageId ?? undefined,
    bindingId: bindingId ?? undefined,
    templateVersionId: templateVersionId ?? undefined,
    limit: 100,
  });

  const filters = [
    providerGroupId ? `providerGroupId=${providerGroupId}` : null,
    messageId ? `messageId=${messageId}` : null,
    bindingId ? `bindingId=${bindingId}` : null,
    templateVersionId ? `templateVersionId=${templateVersionId}` : null,
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Runtime runs"
        description="Per-message container executions with image selection, duration, and failure details."
      />

      {filters.length ? (
        <Notice title="Filters" tone="info">
          <p className="font-mono text-xs">{filters.join(" · ")}</p>
        </Notice>
      ) : null}

      <Card className="overflow-hidden">
        <CardContent className="p-0 pt-0">
          <SimpleTable
            data={runs}
            emptyMessage="No runtime runs recorded yet."
            columns={[
              {
                header: "Run",
                cell: (run) => (
                  <Link
                    href={`/audit/runs/${encodeURIComponent(run.id)}`}
                    className="font-mono text-xs text-primary hover:underline"
                  >
                    {run.id}
                  </Link>
                ),
              },
              {
                header: "Status",
                cell: (run) => <StatusBadge status={run.status} />,
              },
              {
                header: "Group",
                cell: (run) => (
                  <code className="rounded-sm border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                    {run.providerGroupId}
                  </code>
                ),
              },
              {
                header: "Image",
                cell: (run) => (
                  <span className="font-mono text-[11px] text-foreground">
                    {run.imageRef}
                  </span>
                ),
              },
              {
                header: "Duration",
                cell: (run) => (
                  <span className="text-sm text-muted-foreground">
                    {typeof run.durationMs === "number" ? `${run.durationMs}ms` : "n/a"}
                  </span>
                ),
              },
              {
                header: "Started",
                cell: (run) => (
                  <span className="text-sm text-muted-foreground">
                    {formatDateTime(run.startedAt)}
                  </span>
                ),
              },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}

