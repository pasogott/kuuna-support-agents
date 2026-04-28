import {
  auditEvents,
  bindingTimeline,
  bindings,
  groupAssignments,
  mediaAssets,
  messages,
  messageVersions,
  promptAssets,
  runtimeDebugStatus,
  templateVersions,
  templates,
  toolCatalog,
  traceDetails,
  users,
} from "@/lib/api-client/mock-data";
import type {
  AuditEvent,
  BindingTimelineEvent,
  GroupAssignment,
  GroupBinding,
  GroupTemplate,
  KnownProviderGroup,
  KnowledgeDoc,
  MediaAsset,
  MessageRecord,
  MessageVersion,
  PromptAsset,
  RuntimeDebugStatus,
  RuntimeRun,
  StaffUser,
  TemplateBuild,
  TemplateBuildStatus,
  WorkflowStatus,
  TemplateVersion,
  ToolCatalogItem,
  TraceDetail,
} from "@/lib/api-client/types";
import {
  fetchAuditEvents,
  fetchBinding,
  fetchBindingTimeline,
  fetchBindings,
  fetchGroupAssignments,
  fetchKnownProviderGroups,
  fetchMediaAssets,
  fetchMessageVersions,
  fetchMessages,
  fetchPromptAssets,
  fetchRuntimeDebugStatus,
  fetchTemplate,
  fetchTemplates,
  fetchTemplateVersions,
  fetchTools,
  fetchTraceDetail,
  fetchUsers,
} from "@/lib/db/dashboard-repository";

const BACKEND_URL_CANDIDATES = [
  process.env.BACKEND_BASE_URL,
  process.env.NEXT_PUBLIC_API_BASE_URL,
  "http://backend:8000",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://host.docker.internal:8000",
]
  .filter((value): value is string => Boolean(value))
  .filter((value, index, self) => self.indexOf(value) === index);

type IngestedKnowledgeDocResponse = {
  id: string;
  doc_key: string;
  scope: "common" | "group";
  provider_group_id?: string | null;
  title: string;
  status: string;
  updated_at: string;
  updated_by: string;
  chunk_count: number;
};

class ApiContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiContractError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function validateIngestedKnowledgeDoc(
  value: unknown,
  options: { path: string; index: number },
): IngestedKnowledgeDocResponse {
  const { path, index } = options;
  if (!isRecord(value)) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}]: expected object, received ${typeof value}`,
    );
  }

  const id = value.id;
  const docKey = value.doc_key;
  const scope = value.scope;
  const title = value.title;
  const status = value.status;
  const updatedAt = value.updated_at;
  const updatedBy = value.updated_by;
  const chunkCount = value.chunk_count;
  const providerGroupId = value.provider_group_id;

  if (typeof id !== "string" || !id.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].id: expected non-empty string`,
    );
  }

  if (typeof docKey !== "string" || !docKey.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].doc_key: expected non-empty string`,
    );
  }

  if (scope !== "common" && scope !== "group") {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].scope: expected 'common'|'group', received ${String(scope)}`,
    );
  }

  if (typeof title !== "string" || !title.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].title: expected non-empty string`,
    );
  }

  if (typeof status !== "string" || !status.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].status: expected non-empty string`,
    );
  }

  if (typeof updatedAt !== "string" || !updatedAt.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].updated_at: expected non-empty string`,
    );
  }

  if (typeof updatedBy !== "string" || !updatedBy.trim()) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].updated_by: expected non-empty string`,
    );
  }

  if (typeof chunkCount !== "number" || Number.isNaN(chunkCount)) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].chunk_count: expected number`,
    );
  }

  if (
    providerGroupId !== undefined &&
    providerGroupId !== null &&
    typeof providerGroupId !== "string"
  ) {
    throw new ApiContractError(
      `Knowledge API contract mismatch at ${path}[${index}].provider_group_id: expected string|null`,
    );
  }

  return {
    id,
    doc_key: docKey,
    scope,
    provider_group_id: providerGroupId,
    title,
    status,
    updated_at: updatedAt,
    updated_by: updatedBy,
    chunk_count: chunkCount,
  };
}

function delay<T>(value: T, ms = 30): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

function toWorkflowStatus(value: string): WorkflowStatus {
  switch (value) {
    case "draft":
    case "ready":
    case "published":
    case "archived":
    case "active":
    case "inactive":
    case "provisioning":
    case "failed":
    case "queued":
    case "processing":
    case "running":
    case "succeeded":
    case "cancelled":
      return value;
    default:
      return "draft";
  }
}

function getInternalOpsToken(): string | undefined {
  return process.env.DASHBOARD_INTERNAL_OPS_TOKEN ?? process.env.INTERNAL_OPS_TOKEN;
}

function toTemplateBuildStatus(value: string): TemplateBuildStatus {
  switch (value) {
    case "queued":
    case "running":
    case "succeeded":
    case "failed":
    case "cancelled":
      return value;
    default:
      return "failed";
  }
}

function validateTemplateBuild(value: unknown, options: { path: string; index: number }): TemplateBuild {
  const { path, index } = options;

  if (!isRecord(value)) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}]: expected object, received ${typeof value}`,
    );
  }

  const id = value.id;
  const templateId = value.template_id;
  const templateVersionId = value.template_version_id;
  const status = value.status;
  const imageRef = value.image_ref;
  const imageTag = value.image_tag;
  const buildInputs = value.build_inputs;
  const logsRef = value.logs_ref;
  const createdAt = value.created_at;
  const updatedAt = value.updated_at;

  if (typeof id !== "string" || !id.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].id: expected non-empty string`,
    );
  }

  if (typeof templateId !== "string" || !templateId.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].template_id: expected non-empty string`,
    );
  }

  if (typeof templateVersionId !== "string" || !templateVersionId.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].template_version_id: expected non-empty string`,
    );
  }

  if (typeof status !== "string" || !status.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].status: expected non-empty string`,
    );
  }

  if (imageRef !== undefined && imageRef !== null && typeof imageRef !== "string") {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].image_ref: expected string|null`,
    );
  }

  if (imageTag !== undefined && imageTag !== null && typeof imageTag !== "string") {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].image_tag: expected string|null`,
    );
  }

  if (!isRecord(buildInputs)) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].build_inputs: expected object`,
    );
  }

  if (logsRef !== undefined && logsRef !== null && typeof logsRef !== "string") {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].logs_ref: expected string|null`,
    );
  }

  if (typeof createdAt !== "string" || !createdAt.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].created_at: expected non-empty string`,
    );
  }

  if (typeof updatedAt !== "string" || !updatedAt.trim()) {
    throw new ApiContractError(
      `Template build API contract mismatch at ${path}[${index}].updated_at: expected non-empty string`,
    );
  }

  return {
    id,
    templateId,
    templateVersionId,
    status: toTemplateBuildStatus(status),
    imageRef: typeof imageRef === "string" && imageRef.trim() ? imageRef : undefined,
    imageTag: typeof imageTag === "string" && imageTag.trim() ? imageTag : undefined,
    buildInputs,
    logsRef: typeof logsRef === "string" && logsRef.trim() ? logsRef : undefined,
    createdAt,
    updatedAt,
  };
}

async function fetchTemplateBuildsFromBackend(
  templateId: string,
  versionId: string,
): Promise<TemplateBuild[]> {
  const token = getInternalOpsToken();
  if (!token) {
    return [];
  }

  const path = `/internal/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(versionId)}/builds`;
  const errors: string[] = [];

  for (const backendBaseUrl of BACKEND_URL_CANDIDATES) {
    const normalizedBaseUrl = backendBaseUrl.replace(/\/$/, "");

    try {
      const response = await fetch(`${normalizedBaseUrl}${path}`, {
        method: "GET",
        headers: {
          "X-Internal-Token": token,
        },
        cache: "no-store",
      });

      if (!response.ok) {
        const body = await response.text();
        errors.push(`${normalizedBaseUrl} -> ${response.status}: ${body}`);
        continue;
      }

      const payload = (await response.json()) as unknown;
      if (!isRecord(payload) || !Array.isArray(payload.items)) {
        throw new ApiContractError(`Template build API contract mismatch at ${path}: expected { items: [] }`);
      }

      return payload.items.map((item, index) => validateTemplateBuild(item, { path: `${path}.items`, index }));
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      errors.push(`${normalizedBaseUrl} -> ${reason}`);
    }
  }

  throw new Error(errors.join(" | ") || "no-backend-url");
}

function validateRuntimeRun(value: unknown, options: { path: string; index: number }): RuntimeRun {
  const { path, index } = options;
  if (!isRecord(value)) {
    throw new ApiContractError(
      `Runtime run API contract mismatch at ${path}[${index}]: expected object, received ${typeof value}`,
    );
  }

  const id = value.id;
  const providerGroupId = value.provider_group_id;
  const messageId = value.message_id;
  const bindingId = value.binding_id;
  const templateVersionId = value.template_version_id;
  const templateBuildId = value.template_build_id;
  const imageRef = value.image_ref;
  const status = value.status;
  const startedAt = value.started_at;
  const finishedAt = value.finished_at;
  const durationMs = value.duration_ms;
  const error = value.error;
  const execution = value.execution;

  if (typeof id !== "string" || !id.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].id`);
  }
  if (typeof providerGroupId !== "string" || !providerGroupId.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].provider_group_id`);
  }
  if (messageId !== null && messageId !== undefined && typeof messageId !== "string") {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].message_id`);
  }
  if (typeof bindingId !== "string" || !bindingId.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].binding_id`);
  }
  if (typeof templateVersionId !== "string" || !templateVersionId.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].template_version_id`);
  }
  if (templateBuildId !== null && templateBuildId !== undefined && typeof templateBuildId !== "string") {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].template_build_id`);
  }
  if (typeof imageRef !== "string" || !imageRef.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].image_ref`);
  }
  if (typeof status !== "string" || !status.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].status`);
  }
  if (typeof startedAt !== "string" || !startedAt.trim()) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].started_at`);
  }
  if (finishedAt !== null && finishedAt !== undefined && typeof finishedAt !== "string") {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].finished_at`);
  }
  if (durationMs !== null && durationMs !== undefined && typeof durationMs !== "number") {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].duration_ms`);
  }
  if (error !== null && error !== undefined && typeof error !== "string") {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].error`);
  }
  if (!isRecord(execution)) {
    throw new ApiContractError(`Runtime run API contract mismatch at ${path}[${index}].execution`);
  }

  const normalizedStatus =
    status === "started" || status === "succeeded" || status === "failed" || status === "timeout"
      ? status
      : "failed";

  return {
    id,
    providerGroupId,
    messageId: typeof messageId === "string" && messageId.trim() ? messageId : undefined,
    bindingId,
    templateVersionId,
    templateBuildId: typeof templateBuildId === "string" && templateBuildId.trim() ? templateBuildId : undefined,
    imageRef,
    status: normalizedStatus,
    startedAt,
    finishedAt: typeof finishedAt === "string" && finishedAt.trim() ? finishedAt : undefined,
    durationMs: typeof durationMs === "number" ? durationMs : undefined,
    error: typeof error === "string" && error.trim() ? error : undefined,
    execution,
  };
}

async function fetchRuntimeRunsFromBackend(params: {
  providerGroupId?: string;
  messageId?: string;
  templateVersionId?: string;
  bindingId?: string;
  limit?: number;
}): Promise<RuntimeRun[]> {
  const token = getInternalOpsToken();
  if (!token) {
    return [];
  }

  const qs = new URLSearchParams();
  if (params.providerGroupId) qs.set("provider_group_id", params.providerGroupId);
  if (params.messageId) qs.set("message_id", params.messageId);
  if (params.templateVersionId) qs.set("template_version_id", params.templateVersionId);
  if (params.bindingId) qs.set("binding_id", params.bindingId);
  if (params.limit) qs.set("limit", String(params.limit));

  const path = `/internal/runtime-runs${qs.size ? `?${qs.toString()}` : ""}`;
  const errors: string[] = [];

  for (const backendBaseUrl of BACKEND_URL_CANDIDATES) {
    const normalizedBaseUrl = backendBaseUrl.replace(/\/$/, "");
    try {
      const response = await fetch(`${normalizedBaseUrl}${path}`, {
        method: "GET",
        headers: { "X-Internal-Token": token },
        cache: "no-store",
      });
      if (!response.ok) {
        const body = await response.text();
        errors.push(`${normalizedBaseUrl} -> ${response.status}: ${body}`);
        continue;
      }
      const payload = (await response.json()) as unknown;
      if (!isRecord(payload) || !Array.isArray(payload.items)) {
        throw new ApiContractError(`Runtime run API contract mismatch at ${path}: expected { items: [] }`);
      }
      return payload.items.map((item, index) => validateRuntimeRun(item, { path: `${path}.items`, index }));
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      errors.push(`${normalizedBaseUrl} -> ${reason}`);
    }
  }

  throw new Error(errors.join(" | ") || "no-backend-url");
}

async function fetchRuntimeRunFromBackend(runId: string): Promise<RuntimeRun | undefined> {
  const token = getInternalOpsToken();
  if (!token) {
    return undefined;
  }

  const path = `/internal/runtime-runs/${encodeURIComponent(runId)}`;
  const errors: string[] = [];

  for (const backendBaseUrl of BACKEND_URL_CANDIDATES) {
    const normalizedBaseUrl = backendBaseUrl.replace(/\/$/, "");
    try {
      const response = await fetch(`${normalizedBaseUrl}${path}`, {
        method: "GET",
        headers: { "X-Internal-Token": token },
        cache: "no-store",
      });
      if (!response.ok) {
        const body = await response.text();
        errors.push(`${normalizedBaseUrl} -> ${response.status}: ${body}`);
        continue;
      }
      const payload = (await response.json()) as unknown;
      return validateRuntimeRun(payload, { path, index: 0 });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      errors.push(`${normalizedBaseUrl} -> ${reason}`);
    }
  }

  throw new Error(errors.join(" | ") || "no-backend-url");
}

function mapIngestedKnowledgeDoc(doc: IngestedKnowledgeDocResponse): KnowledgeDoc {
  return {
    id: doc.id,
    docKey: doc.doc_key,
    scope: doc.scope === "group" ? "group" : "common",
    providerGroupId: doc.provider_group_id ?? undefined,
    title: doc.title,
    status: toWorkflowStatus(doc.status),
    updatedAt: doc.updated_at,
    updatedBy: doc.updated_by,
    chunkCount: doc.chunk_count,
  };
}

async function fetchBackendKnowledge(path: string): Promise<IngestedKnowledgeDocResponse[]> {
  const errors: string[] = [];

  for (const backendBaseUrl of BACKEND_URL_CANDIDATES) {
    const normalizedBaseUrl = backendBaseUrl.replace(/\/$/, "");

    try {
      const response = await fetch(`${normalizedBaseUrl}${path}`, {
        method: "GET",
        cache: "no-store",
      });

      if (!response.ok) {
        const body = await response.text();
        errors.push(`${normalizedBaseUrl} -> ${response.status}: ${body}`);
        continue;
      }

      const payload = (await response.json()) as unknown;
      if (!Array.isArray(payload)) {
        throw new ApiContractError(
          `Knowledge API contract mismatch at ${path}: expected array response`,
        );
      }

      return payload.map((item, index) =>
        validateIngestedKnowledgeDoc(item, { path, index }),
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      errors.push(`${normalizedBaseUrl} -> ${reason}`);
    }
  }

  throw new Error(errors.join(" | ") || "no-backend-url");
}

async function withFallback<T>(
  label: string,
  dbLoader: () => Promise<T>,
  fallbackLoader: () => Promise<T>,
): Promise<T> {
  try {
    return await dbLoader();
  } catch (error) {
    console.warn(`[dashboard-api] ${label}: falling back to mock data`, error);
    return fallbackLoader();
  }
}

export async function listTemplates(): Promise<GroupTemplate[]> {
  return withFallback("listTemplates", fetchTemplates, () => delay(templates));
}

export async function getTemplate(templateId: string): Promise<GroupTemplate | undefined> {
  return withFallback(
    "getTemplate",
    () => fetchTemplate(templateId),
    () => delay(templates.find((item) => item.id === templateId)),
  );
}

export async function listTemplateVersions(
  templateId: string,
): Promise<TemplateVersion[]> {
  return withFallback(
    "listTemplateVersions",
    () => fetchTemplateVersions(templateId),
    () =>
      delay(
        templateVersions
          .filter((item) => item.templateId === templateId)
          .sort((a, b) => b.versionNo - a.versionNo),
      ),
  );
}

export async function listTemplateBuilds(
  templateId: string,
  versionId: string,
): Promise<TemplateBuild[]> {
  try {
    return await fetchTemplateBuildsFromBackend(templateId, versionId);
  } catch (error) {
    console.warn("[dashboard-api] listTemplateBuilds: backend internal endpoint failed", error);
    return [];
  }
}

export async function listRuntimeRuns(params: {
  providerGroupId?: string;
  messageId?: string;
  templateVersionId?: string;
  bindingId?: string;
  limit?: number;
}): Promise<RuntimeRun[]> {
  try {
    return await fetchRuntimeRunsFromBackend(params);
  } catch (error) {
    console.warn("[dashboard-api] listRuntimeRuns: backend internal endpoint failed", error);
    return [];
  }
}

export async function getRuntimeRun(runId: string): Promise<RuntimeRun | undefined> {
  try {
    return await fetchRuntimeRunFromBackend(runId);
  } catch (error) {
    console.warn("[dashboard-api] getRuntimeRun: backend internal endpoint failed", error);
    return undefined;
  }
}

export async function listBindings(): Promise<GroupBinding[]> {
  return withFallback("listBindings", fetchBindings, () => delay(bindings));
}

export async function getRuntimeDebugStatus(): Promise<RuntimeDebugStatus> {
  return withFallback("getRuntimeDebugStatus", fetchRuntimeDebugStatus, () =>
    delay(runtimeDebugStatus),
  );
}

export async function listTools(): Promise<ToolCatalogItem[]> {
  return withFallback(
    "listTools",
    async () => {
      const items = await fetchTools();
      return items.length ? items : delay(toolCatalog);
    },
    () => delay(toolCatalog),
  );
}

export async function getBinding(bindingId: string): Promise<GroupBinding | undefined> {
  return withFallback(
    "getBinding",
    () => fetchBinding(bindingId),
    () => delay(bindings.find((item) => item.id === bindingId)),
  );
}

export async function listBindingTimeline(
  bindingId: string,
): Promise<BindingTimelineEvent[]> {
  return withFallback(
    "listBindingTimeline",
    () => fetchBindingTimeline(bindingId),
    () =>
      delay(
        bindingTimeline
          .filter((item) => item.bindingId === bindingId)
          .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)),
      ),
  );
}

export async function listKnownProviderGroups(): Promise<KnownProviderGroup[]> {
  return withFallback(
    "listKnownProviderGroups",
    fetchKnownProviderGroups,
    () => {
      const map = new Map<string, KnownProviderGroup>();

      for (const binding of bindings) {
        map.set(binding.providerGroupId, {
          providerGroupId: binding.providerGroupId,
          groupTitle: binding.groupTitle,
          lastSeenAt: binding.updatedAt,
          sources: ["binding"],
        });
      }

      for (const message of messages) {
        const existing = map.get(message.providerGroupId);
        if (existing) {
          if (!existing.sources.includes("message")) {
            existing.sources.push("message");
          }
          if (!existing.lastSeenAt || message.createdAt > existing.lastSeenAt) {
            existing.lastSeenAt = message.createdAt;
          }
          continue;
        }

        map.set(message.providerGroupId, {
          providerGroupId: message.providerGroupId,
          groupTitle: message.providerGroupId,
          lastSeenAt: message.createdAt,
          sources: ["message"],
        });
      }

      return delay([...map.values()]);
    },
  );
}

export async function listPromptAssets(instanceId?: string): Promise<PromptAsset[]> {
  return withFallback(
    "listPromptAssets",
    () => fetchPromptAssets(instanceId),
    () => {
      const scoped = instanceId
        ? promptAssets.filter((item) => item.instanceId === instanceId)
        : promptAssets;
      return delay(scoped);
    },
  );
}

export async function listKnowledgeDocs(
  scope?: "common" | "group",
  providerGroupId?: string,
): Promise<KnowledgeDoc[]> {
  try {
    if (scope === "common") {
      const commonDocs = await fetchBackendKnowledge("/knowledge/ingested/common-docs");
      return commonDocs.map(mapIngestedKnowledgeDoc);
    }

    if (scope === "group") {
      const groupPath = providerGroupId
        ? `/knowledge/ingested/group-docs/${encodeURIComponent(providerGroupId)}`
        : "/knowledge/ingested/group-docs";
      const groupDocs = await fetchBackendKnowledge(groupPath);
      return groupDocs.map(mapIngestedKnowledgeDoc);
    }

    const [commonDocs, groupDocs] = await Promise.all([
      fetchBackendKnowledge("/knowledge/ingested/common-docs"),
      fetchBackendKnowledge("/knowledge/ingested/group-docs"),
    ]);

    return [...commonDocs, ...groupDocs].map(mapIngestedKnowledgeDoc);
  } catch (error) {
    if (error instanceof ApiContractError) {
      console.error("[dashboard-api] listKnowledgeDocs: contract violation", error);
      throw error;
    }

    console.warn("[dashboard-api] listKnowledgeDocs: backend ingested endpoint failed", error);
    return [];
  }
}

export async function listMessages(providerGroupId?: string): Promise<MessageRecord[]> {
  return withFallback(
    "listMessages",
    () => fetchMessages(providerGroupId),
    () =>
      delay(
        messages.filter((item) =>
          providerGroupId ? item.providerGroupId === providerGroupId : true,
        ),
      ),
  );
}

export async function listMessageVersions(messageId: string): Promise<MessageVersion[]> {
  return withFallback(
    "listMessageVersions",
    () => fetchMessageVersions(messageId),
    () =>
      delay(
        messageVersions
          .filter((item) => item.messageId === messageId)
          .sort((a, b) => b.versionNo - a.versionNo),
      ),
  );
}

export async function listMediaAssets(messageId: string): Promise<MediaAsset[]> {
  return withFallback(
    "listMediaAssets",
    () => fetchMediaAssets(messageId),
    () => delay(mediaAssets.filter((item) => item.messageId === messageId)),
  );
}

export async function listAuditEvents(): Promise<AuditEvent[]> {
  return withFallback("listAuditEvents", fetchAuditEvents, () => delay(auditEvents));
}

export async function getTraceDetail(
  traceId: string,
): Promise<TraceDetail | undefined> {
  return withFallback(
    "getTraceDetail",
    () => fetchTraceDetail(traceId),
    () => delay(traceDetails.find((item) => item.traceId === traceId)),
  );
}

export async function listUsers(): Promise<StaffUser[]> {
  return withFallback("listUsers", fetchUsers, () => delay(users));
}

export async function listGroupAssignments(): Promise<GroupAssignment[]> {
  return withFallback(
    "listGroupAssignments",
    fetchGroupAssignments,
    () => delay(groupAssignments),
  );
}
