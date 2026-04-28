import { notFound } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Notice } from "@/components/ui/notice";
import { PageHeader } from "@/components/ui/page-header";
import { getTraceDetail } from "@/lib/api-client";
import Link from "next/link";

type Params = Promise<{ traceId: string }>;

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

export default async function TraceDetailPage({
  params,
}: {
  params: Params;
}) {
  const { traceId } = await params;
  const detail = await getTraceDetail(traceId);

  if (!detail) {
    notFound();
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={`Trace ${detail.traceId}`}
        description="End-to-end correlation across ingest, retrieval, model path, and outbound intent."
        actions={
          detail.providerGroupId ? (
            <Link
              href={`/audit/runs?providerGroupId=${encodeURIComponent(detail.providerGroupId)}`}
              className="text-sm text-primary hover:underline"
            >
              View runtime runs
            </Link>
          ) : null
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Identifiers</CardTitle>
            <CardDescription>
              Stable references for cross-system correlation.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pb-6">
            <MonoRow label="Provider group" value={detail.providerGroupId} />
            <MonoRow label="Inbound event" value={detail.inboundEventId} />
            <MonoRow label="Outbound intent" value={detail.outboundIntentId} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Model failover path</CardTitle>
            <CardDescription>
              Order of models the runtime attempted for this trace.
            </CardDescription>
          </CardHeader>
          <CardContent className="pb-6">
            <p className="font-mono text-sm text-foreground">
              {detail.modelPath.join(" → ")}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Retrieval references</CardTitle>
          <CardDescription>
            Knowledge sources matched during context assembly.
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-6">
          {detail.retrievalRefs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No retrieval references recorded.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {detail.retrievalRefs.map((reference) => (
                <li
                  key={reference}
                  className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-xs text-foreground"
                >
                  {reference}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Notice title="Privacy" tone="info">
        Dashboard trace view intentionally shows metadata only. Raw user content
        is excluded from logs and Sentry in MVP.
      </Notice>
    </div>
  );
}
