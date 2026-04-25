import Link from "next/link";
import { notFound } from "next/navigation";

import { SimpleTable } from "@/components/data-table/simple-table";
import { StatusBadge } from "@/components/status/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FormActions, FormRow } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { getTemplate, listTemplateVersions } from "@/lib/api-client";
import {
  createTemplateDraftVersionAction,
  publishTemplateVersionAction,
} from "@/lib/templates/actions";
import { formatDateTime } from "@/lib/utils/format";

type Params = Promise<{ templateId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function getSingleParam(
  value: string | string[] | undefined,
): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function defaultModelChain(
  versions: Array<{ modelChain: string[] }>,
): string {
  const latestWithChain = versions.find(
    (version) => version.modelChain.length > 0,
  );
  if (!latestWithChain) {
    return "gpt-4.1-mini";
  }
  return latestWithChain.modelChain.join(", ");
}

function csvOrEmpty(values: string[] | undefined): string {
  return values?.length ? values.join(", ") : "";
}

export default async function TemplateDetailPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { templateId } = await params;
  const search = await searchParams;
  const created = getSingleParam(search.created);
  const draftCreated = getSingleParam(search.draft);
  const published = getSingleParam(search.published);
  const versionId = getSingleParam(search.versionId);
  const cloneFromVersionId = getSingleParam(search.cloneFromVersionId);
  const error = getSingleParam(search.error);

  const [template, versions] = await Promise.all([
    getTemplate(templateId),
    listTemplateVersions(templateId),
  ]);

  if (!template) {
    notFound();
  }

  const modelChainDefault = defaultModelChain(versions);
  const cloneSource = cloneFromVersionId
    ? versions.find((version) => version.id === cloneFromVersionId)
    : undefined;
  const systemPromptDefault =
    "You are a concise WhatsApp support assistant. Reply in clear German and provide concrete next steps.";
  const modelChainPrefill = cloneSource?.modelChain?.length
    ? csvOrEmpty(cloneSource.modelChain)
    : modelChainDefault;
  const allowedToolsPrefill = "echo, uppercase";
  const egressModePrefill = cloneSource?.egressPolicy ?? "restricted";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={template.displayName}
        description={`Template key: ${template.key}`}
        actions={
          <Button variant="outline" asChild>
            <Link href="/bindings/create">
              <span>Go to binding</span>
            </Link>
          </Button>
        }
      />

      {created === "1" ? (
        <Notice title="Template created" tone="success">
          Next step: create a draft version, then publish it before binding
          groups.
        </Notice>
      ) : null}

      {draftCreated === "1" ? (
        <Notice title="Draft version created" tone="success">
          {versionId ? (
            <p>
              Version ID:{" "}
              <code className="rounded-sm border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {versionId}
              </code>
            </p>
          ) : null}
          <p>Publish it so staff can bind WhatsApp groups with this template.</p>
        </Notice>
      ) : null}

      {published === "1" ? (
        <Notice title="Template version published" tone="success">
          {versionId ? (
            <p>
              Active version:{" "}
              <code className="rounded-sm border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {versionId}
              </code>
            </p>
          ) : null}
          <p>You can now bind a group using this version.</p>
        </Notice>
      ) : null}

      {error ? (
        <Notice title="Template workflow failed" tone="warning">
          {error}
        </Notice>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Configuration summary</CardTitle>
          <CardDescription>{template.description}</CardDescription>
        </CardHeader>
        <CardContent className="pb-6">
          <p className="text-sm text-muted-foreground">
            Published version ID:{" "}
            <code className="rounded-sm border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
              {template.publishedVersionId || "n/a"}
            </code>
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            Flow: create draft → (optionally clone/edit) → publish → bind group.
          </p>
        </CardContent>
      </Card>

      <Card>
        <div id="create-draft" />
        <CardHeader>
          <CardTitle>Create draft version</CardTitle>
          <CardDescription>
            Start from defaults or clone an existing version using the timeline actions below.
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-6">
          <form
            action={createTemplateDraftVersionAction}
            className="flex flex-col gap-4"
          >
            <input type="hidden" name="templateId" value={template.id} />

            <FormRow label="System prompt" htmlFor="systemPrompt">
              <Textarea
                id="systemPrompt"
                name="systemPrompt"
                defaultValue={systemPromptDefault}
                rows={6}
              />
            </FormRow>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <FormRow
                label="Model chain"
                htmlFor="modelChain"
                hint="Comma-separated, in failover order."
              >
                <Input
                  id="modelChain"
                  name="modelChain"
                  defaultValue={modelChainPrefill}
                  placeholder="gpt-4.1-mini, gpt-4.1"
                />
              </FormRow>

              <FormRow
                label="Allowed tools"
                htmlFor="allowedTools"
                hint="Comma-separated tool keys."
              >
                <Input
                  id="allowedTools"
                  name="allowedTools"
                  defaultValue={allowedToolsPrefill}
                  placeholder="echo, uppercase"
                />
              </FormRow>
            </div>

            <FormRow label="Egress mode" htmlFor="egressMode">
              <Select
                id="egressMode"
                name="egressMode"
                defaultValue={egressModePrefill}
              >
                <option value="restricted">restricted</option>
                <option value="strict">strict</option>
                <option value="allow-all">allow-all</option>
              </Select>
            </FormRow>

            <FormActions>
              <Button type="submit">Create draft</Button>
            </FormActions>
          </form>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <div id="timeline" />
        <CardHeader>
          <CardTitle>Version timeline</CardTitle>
          <CardDescription>
            All template versions with their model and egress configuration.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0 pt-4">
          <SimpleTable
            data={versions}
            emptyMessage="No versions yet."
            columns={[
              {
                header: "Version",
                cell: (version) => (
                  <Badge variant="outline">v{version.versionNo}</Badge>
                ),
              },
              {
                header: "Status",
                cell: (version) => <StatusBadge status={version.status} />,
              },
              {
                header: "Model failover",
                cell: (version) =>
                  version.modelChain.length ? (
                    <span className="font-mono text-xs text-foreground">
                      {version.modelChain.join(" → ")}
                    </span>
                  ) : (
                    <span className="text-sm text-muted-foreground">n/a</span>
                  ),
              },
              {
                header: "Tool profile",
                cell: (version) => (
                  <span className="text-sm text-foreground">
                    {version.toolProfile || "default"}
                  </span>
                ),
              },
              {
                header: "Egress",
                cell: (version) => (
                  <span className="text-sm text-foreground">
                    {version.egressPolicy || "default"}
                  </span>
                ),
              },
              {
                header: "Updated",
                cell: (version) => (
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(version.updatedAt)} by {version.updatedBy}
                  </span>
                ),
              },
              {
                header: "Actions",
                cell: (version) => {
                  const cloneHref = `/templates/${encodeURIComponent(template.id)}?cloneFromVersionId=${encodeURIComponent(version.id)}#create-draft`;

                  if (
                    version.status !== "draft" &&
                    version.status !== "ready"
                  ) {
                    return (
                      <Button type="button" variant="outline" size="sm" asChild>
                        <Link href={cloneHref}>Clone</Link>
                      </Button>
                    );
                  }

                  return (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button type="button" variant="outline" size="sm" asChild>
                        <Link href={cloneHref}>Clone</Link>
                      </Button>
                      <form action={publishTemplateVersionAction}>
                        <input
                          type="hidden"
                          name="templateId"
                          value={template.id}
                        />
                        <input type="hidden" name="versionId" value={version.id} />
                        <Button type="submit" variant="outline" size="sm">
                          Publish
                        </Button>
                      </form>
                    </div>
                  );
                },
              },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}
