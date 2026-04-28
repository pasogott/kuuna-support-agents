import "server-only";

import { dbQuery, isMissingRelationError } from "@/lib/db/postgres";
import type {
  AuditEvent,
  BindingTimelineEvent,
  GroupAssignment,
  GroupBinding,
  GroupTemplate,
  KnownProviderGroup,
  MediaAsset,
  MessageRecord,
  MessageVersion,
  PromptAsset,
  StaffUser,
  RuntimeDebugStatus,
  TemplateVersion,
  ToolCatalogItem,
  TraceDetail,
  WorkflowStatus,
} from "@/lib/api-client/types";
import { titleFromGroupId } from "@/lib/utils/format";

function toDisplayName(email: string): string {
  const localPart = email.split("@")[0] ?? "staff";
  return localPart
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function toWorkflowStatus(value: string | null | undefined): WorkflowStatus {
  switch (value) {
    case "draft":
    case "ready":
    case "published":
    case "archived":
    case "active":
    case "provisioning":
    case "failed":
    case "queued":
    case "processing":
    case "inactive":
      return value;
    default:
      return "draft";
  }
}

function parseModelChain(input: unknown): string[] {
  if (!input || typeof input !== "object") {
    return [];
  }

  const modelConfig = input as Record<string, unknown>;
  const candidates = [
    modelConfig.failover_chain,
    modelConfig.failoverChain,
    modelConfig.model_chain,
    modelConfig.models,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      const values = candidate.filter((item): item is string => typeof item === "string");
      if (values.length) {
        return values;
      }
    }
  }

  const single = [
    modelConfig.model,
    modelConfig.primary,
    modelConfig.primary_model,
    modelConfig.primaryModel,
  ].find((item): item is string => typeof item === "string" && item.length > 0);

  return single ? [single] : [];
}

function parseToolProfile(input: unknown): string {
  if (!input || typeof input !== "object") {
    return "default";
  }

  const value = (input as Record<string, unknown>).profile;
  if (typeof value === "string" && value.length) {
    return value;
  }

  return "default";
}

function parseAllowedTools(input: unknown): string[] {
  if (!input || typeof input !== "object") {
    return [];
  }

  const toolsConfig = input as Record<string, unknown>;
  const candidates: string[] = [];

  for (const key of ["allowed_tools", "allowedTools"]) {
    const raw = toolsConfig[key];
    if (Array.isArray(raw)) {
      candidates.push(...raw.filter((item): item is string => typeof item === "string"));
    }
  }

  const rawTools = toolsConfig.tools;
  if (Array.isArray(rawTools)) {
    for (const item of rawTools) {
      if (typeof item === "string") {
        candidates.push(item);
      } else if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        if (typeof record.name === "string" && record.enabled !== false) {
          candidates.push(record.name);
        }
      }
    }
  }

  const normalized: string[] = [];
  for (const candidate of candidates) {
    const value = candidate.trim().toLowerCase();
    if (value && !normalized.includes(value)) {
      normalized.push(value);
    }
  }
  return normalized;
}

function parseEgressPolicy(input: unknown): string {
  if (!input || typeof input !== "object") {
    return "default";
  }

  const record = input as Record<string, unknown>;
  const mode = record.mode;
  if (typeof mode === "string" && mode.length) {
    return mode;
  }

  return "default";
}

const RUNTIME_AGENT_URL_CANDIDATES = [
  process.env.RUNTIME_AGENT_BASE_URL,
  process.env.NEXT_PUBLIC_RUNTIME_AGENT_BASE_URL,
  "http://runtime-agent:8100",
  "http://localhost:8100",
  "http://127.0.0.1:8100",
  "http://host.docker.internal:8100",
].filter((value, index, self): value is string => Boolean(value) && self.indexOf(value) === index);

function parseModelPath(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

type DbTemplateRow = {
  id: string;
  key: string;
  display_name: string;
  updated_at: string;
  published_version_id: string | null;
};

export async function fetchTemplates(): Promise<GroupTemplate[]> {
  const rows = await dbQuery<DbTemplateRow>(
    `
    select
      gt.id::text,
      gt.key,
      gt.display_name,
      gt.updated_at::text,
      pv.id::text as published_version_id
    from group_templates gt
    left join lateral (
      select tv.id
      from template_versions tv
      where tv.template_id = gt.id and tv.status = 'published'
      order by tv.version_no desc
      limit 1
    ) as pv on true
    order by gt.updated_at desc
    `,
  );

  return rows.map((row) => ({
    id: row.id,
    key: row.key,
    displayName: row.display_name,
    description: `${row.display_name} template`,
    publishedVersionId: row.published_version_id ?? "",
    updatedAt: row.updated_at,
  }));
}

export async function fetchTemplate(templateId: string): Promise<GroupTemplate | undefined> {
  const rows = await dbQuery<DbTemplateRow>(
    `
    select
      gt.id::text,
      gt.key,
      gt.display_name,
      gt.updated_at::text,
      pv.id::text as published_version_id
    from group_templates gt
    left join lateral (
      select tv.id
      from template_versions tv
      where tv.template_id = gt.id and tv.status = 'published'
      order by tv.version_no desc
      limit 1
    ) as pv on true
    where gt.id = $1::uuid
    limit 1
    `,
    [templateId],
  );

  const row = rows[0];
  if (!row) {
    return undefined;
  }

  return {
    id: row.id,
    key: row.key,
    displayName: row.display_name,
    description: `${row.display_name} template`,
    publishedVersionId: row.published_version_id ?? "",
    updatedAt: row.updated_at,
  };
}

type DbTemplateVersionRow = {
  id: string;
  template_id: string;
  version_no: number;
  status: string;
  system_prompt: string | null;
  model_config: unknown;
  tools_config: unknown;
  egress_policy: unknown;
  updated_at: string;
};

export async function fetchTemplateVersions(templateId: string): Promise<TemplateVersion[]> {
  const rows = await dbQuery<DbTemplateVersionRow>(
    `
    select
      id::text,
      template_id::text,
      version_no,
      status::text,
      system_prompt,
      model_config,
      tools_config,
      egress_policy,
      updated_at::text
    from template_versions
    where template_id = $1::uuid
    order by version_no desc
    `,
    [templateId],
  );

  return rows.map((row) => ({
    id: row.id,
    templateId: row.template_id,
    versionNo: row.version_no,
    status: toWorkflowStatus(row.status),
    systemPrompt: row.system_prompt ?? undefined,
    modelChain: parseModelChain(row.model_config),
    allowedTools: parseAllowedTools(row.tools_config),
    toolProfile: parseToolProfile(row.tools_config),
    egressPolicy: parseEgressPolicy(row.egress_policy),
    updatedAt: row.updated_at,
    updatedBy: "system",
  }));
}

type DbBindingRow = {
  id: string;
  provider_group_id: string;
  template_version_id: string;
  status: string;
  runtime_mode: string | null;
  updated_at: string;
  created_at: string;
};

type DbKnownProviderGroupRow = {
  provider_group_id: string;
  last_seen_at: string | null;
  has_binding: boolean;
  has_message: boolean;
  has_assignment: boolean;
  has_knowledge: boolean;
};

function toRuntimeMode(value: string | null): "on-demand" | "hot" {
  if (value === "hot") {
    return "hot";
  }
  return "on-demand";
}

function bindingRowToModel(row: DbBindingRow): GroupBinding {
  return {
    id: row.id,
    providerGroupId: row.provider_group_id,
    groupTitle: titleFromGroupId(row.provider_group_id),
    templateVersionId: row.template_version_id,
    status: toWorkflowStatus(row.status),
    runtimeMode: toRuntimeMode(row.runtime_mode),
    updatedAt: row.updated_at,
  };
}

type DbToolRow = {
  id: string;
  tool_key: string;
  display_name: string;
  description: string;
  risk_class: "read" | "write" | "admin";
  category: string;
  is_enabled: boolean;
  updated_at: string;
};

export async function fetchTools(): Promise<ToolCatalogItem[]> {
  const rows = await dbQuery<DbToolRow>(
    `
    select
      id::text,
      tool_key,
      display_name,
      description,
      risk_class::text,
      category,
      is_enabled,
      updated_at::text
    from tool_catalog_entries
    order by category asc, risk_class asc, display_name asc
    `,
  );

  return rows.map((row) => ({
    id: row.id,
    toolKey: row.tool_key,
    displayName: row.display_name,
    description: row.description,
    riskClass: row.risk_class,
    category: row.category,
    isEnabled: row.is_enabled,
    updatedAt: row.updated_at,
  }));
}

type DbLatestOutboundModelRow = {
  outbound_intent_id: string;
  created_at: string;
  model_path: unknown;
};

export async function fetchRuntimeDebugStatus(): Promise<RuntimeDebugStatus> {
  let lastModelPath: string[] = [];
  let lastOutboundIntentId: string | undefined;
  let lastOutboundAt: string | undefined;

  try {
    const rows = await dbQuery<DbLatestOutboundModelRow>(
      `
      select
        outbound_intent_id::text,
        created_at::text,
        payload->'metadata'->'model_path' as model_path
      from outbound_intents
      order by created_at desc
      limit 1
      `,
    );

    const latest = rows[0];
    if (latest) {
      lastModelPath = parseModelPath(latest.model_path);
      lastOutboundIntentId = latest.outbound_intent_id;
      lastOutboundAt = latest.created_at;
    }
  } catch (error) {
    if (!isMissingRelationError(error)) {
      throw error;
    }
  }

  let lastError = "runtime-agent unreachable";

  for (const candidate of RUNTIME_AGENT_URL_CANDIDATES) {
    const normalizedBase = candidate.replace(/\/$/, "");
    try {
      const response = await fetch(`${normalizedBase}/debug/status`, {
        method: "GET",
        cache: "no-store",
      });

      if (!response.ok) {
        lastError = `${normalizedBase} -> ${response.status}`;
        continue;
      }

      const payload = (await response.json()) as {
        status?: string;
        openai_configured?: boolean;
        openai_base_url?: string;
        openai_timeout_seconds?: string;
      };

      return {
        runtimeHealth: payload.status === "ok" ? "ok" : "error",
        runtimeUrl: normalizedBase,
        openaiConfigured:
          typeof payload.openai_configured === "boolean" ? payload.openai_configured : null,
        openaiBaseUrl: payload.openai_base_url,
        openaiTimeoutSeconds: payload.openai_timeout_seconds,
        lastModelPath,
        lastModelUsed: lastModelPath[0],
        lastOutboundIntentId,
        lastOutboundAt,
      };
    } catch (error) {
      lastError = `${normalizedBase} -> ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  return {
    runtimeHealth: "unreachable",
    openaiConfigured: null,
    lastModelPath,
    lastModelUsed: lastModelPath[0],
    lastOutboundIntentId,
    lastOutboundAt,
    error: lastError,
  };
}

export async function fetchBindings(): Promise<GroupBinding[]> {
  const rows = await dbQuery<DbBindingRow>(
    `
    select
      gb.id::text,
      gb.provider_group_id,
      gb.template_version_id::text,
      gb.status::text,
      ai.runtime_mode::text as runtime_mode,
      gb.created_at::text,
      gb.updated_at::text
    from group_bindings gb
    left join agent_instances ai on ai.group_binding_id = gb.id
    order by gb.updated_at desc
    `,
  );

  return rows.map(bindingRowToModel);
}

export async function fetchBinding(bindingId: string): Promise<GroupBinding | undefined> {
  const rows = await dbQuery<DbBindingRow>(
    `
    select
      gb.id::text,
      gb.provider_group_id,
      gb.template_version_id::text,
      gb.status::text,
      ai.runtime_mode::text as runtime_mode,
      gb.created_at::text,
      gb.updated_at::text
    from group_bindings gb
    left join agent_instances ai on ai.group_binding_id = gb.id
    where gb.id = $1::uuid
    limit 1
    `,
    [bindingId],
  );

  const row = rows[0];
  return row ? bindingRowToModel(row) : undefined;
}

export async function fetchKnownProviderGroups(): Promise<KnownProviderGroup[]> {
  const rows = await dbQuery<DbKnownProviderGroupRow>(
    `
    with groups as (
      select gb.provider_group_id as provider_group_id,
             max(gb.updated_at)::text as last_seen_at,
             true as has_binding,
             false as has_message,
             false as has_assignment,
             false as has_knowledge
      from group_bindings gb
      group by gb.provider_group_id

      union all

      select m.provider_group_id,
             max(m.created_at)::text as last_seen_at,
             false as has_binding,
             true as has_message,
             false as has_assignment,
             false as has_knowledge
      from messages m
      group by m.provider_group_id

      union all

      select ga.provider_group_id,
             max(ga.created_at)::text as last_seen_at,
             false as has_binding,
             false as has_message,
             true as has_assignment,
             false as has_knowledge
      from group_assignments ga
      group by ga.provider_group_id

      union all

      select kgd.provider_group_id,
             max(kgd.updated_at)::text as last_seen_at,
             false as has_binding,
             false as has_message,
             false as has_assignment,
             true as has_knowledge
      from knowledge_group_docs kgd
      group by kgd.provider_group_id
    )
    select
      provider_group_id,
      max(last_seen_at) as last_seen_at,
      bool_or(has_binding) as has_binding,
      bool_or(has_message) as has_message,
      bool_or(has_assignment) as has_assignment,
      bool_or(has_knowledge) as has_knowledge
    from groups
    group by provider_group_id
    order by max(last_seen_at) desc nulls last, provider_group_id asc
    `,
  );

  return rows.map((row) => {
    const sources: KnownProviderGroup["sources"] = [];
    if (row.has_binding) sources.push("binding");
    if (row.has_message) sources.push("message");
    if (row.has_assignment) sources.push("assignment");
    if (row.has_knowledge) sources.push("knowledge");

    return {
      providerGroupId: row.provider_group_id,
      groupTitle: titleFromGroupId(row.provider_group_id),
      lastSeenAt: row.last_seen_at ?? undefined,
      sources,
    };
  });
}

export async function fetchBindingTimeline(bindingId: string): Promise<BindingTimelineEvent[]> {
  const rows = await dbQuery<DbBindingRow>(
    `
    select
      gb.id::text,
      gb.provider_group_id,
      gb.template_version_id::text,
      gb.status::text,
      ai.runtime_mode::text as runtime_mode,
      gb.created_at::text,
      gb.updated_at::text
    from group_bindings gb
    left join agent_instances ai on ai.group_binding_id = gb.id
    where gb.id = $1::uuid
    limit 1
    `,
    [bindingId],
  );

  const row = rows[0];
  if (!row) {
    return [];
  }

  const events: BindingTimelineEvent[] = [
    {
      id: `${row.id}-created`,
      bindingId: row.id,
      status: "draft",
      label: "Binding created",
      occurredAt: row.created_at,
    },
    {
      id: `${row.id}-current`,
      bindingId: row.id,
      status: toWorkflowStatus(row.status),
      label: `Current status: ${row.status}`,
      occurredAt: row.updated_at,
      details: `Runtime mode ${toRuntimeMode(row.runtime_mode)}`,
    },
  ];

  return events.sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));
}

type DbUserRow = {
  id: string;
  email: string;
  is_active: boolean;
  role: string | null;
};

export async function fetchUsers(): Promise<StaffUser[]> {
  const rows = await dbQuery<DbUserRow>(
    `
    select
      u.id::text,
      u.email,
      u.is_active,
      rr.role
    from users u
    left join lateral (
      select r.name::text as role
      from user_roles ur
      join roles r on r.id = ur.role_id
      where ur.user_id = u.id
      order by case r.name
        when 'owner' then 1
        when 'admin' then 2
        when 'operator' then 3
        when 'viewer' then 4
        else 99 end
      limit 1
    ) as rr on true
    order by u.created_at asc
    `,
  );

  return rows.map((row) => ({
    id: row.id,
    email: row.email,
    displayName: toDisplayName(row.email),
    role: (row.role ?? "viewer") as StaffUser["role"],
    active: row.is_active,
  }));
}

type DbAssignmentRow = {
  id: string;
  user_id: string;
  email: string;
  provider_group_id: string;
};

export async function fetchGroupAssignments(): Promise<GroupAssignment[]> {
  const rows = await dbQuery<DbAssignmentRow>(
    `
    select
      ga.id::text,
      ga.user_id::text,
      u.email,
      ga.provider_group_id
    from group_assignments ga
    join users u on u.id = ga.user_id
    order by ga.provider_group_id asc
    `,
  );

  return rows.map((row) => ({
    id: row.id,
    userId: row.user_id,
    user: row.email,
    providerGroupId: row.provider_group_id,
    groupTitle: titleFromGroupId(row.provider_group_id),
  }));
}

type DbMessageRow = {
  id: string;
  provider_group_id: string;
  sender_provider_user_id: string | null;
  sender_phone: string | null;
  sender_pushname: string | null;
  latest_version_no: number;
  created_at: string;
  preview: string | null;
  is_deleted: boolean | null;
  has_media: boolean;
};

export async function fetchMessages(providerGroupId?: string): Promise<MessageRecord[]> {
  const rows = await dbQuery<DbMessageRow>(
    `
    select
      m.id::text,
      m.provider_group_id,
      m.sender_provider_user_id,
      m.latest_version_no,
      m.created_at::text,
      mv.preview_text as preview,
      mv.is_deleted,
      coalesce(
        mv.raw_event #>> '{Info,MessageSource,SenderAlt,User}',
        mv.raw_event #>> '{Info,MessageSource,Sender,User}'
      ) as sender_phone,
      mv.raw_event #>> '{Info,Pushname}' as sender_pushname,
      exists (
        select 1 from media_assets ma where ma.message_id = m.id
      ) as has_media
    from messages m
    left join lateral (
      select
        text_content,
        is_deleted,
        raw_event,
        case
          when is_deleted then coalesce(
            (
              select mv2.text_content
              from message_versions mv2
              where mv2.message_id = m.id
                and mv2.is_deleted is false
                and mv2.text_content is not null
                and btrim(mv2.text_content) <> ''
              order by mv2.version_no desc
              limit 1
            ),
            '[deleted]'
          )
          when text_content is not null and btrim(text_content) <> '' then text_content
          when raw_event #>> '{Info,Type}' = 'reaction' then '[reaction]'
          when raw_event #>> '{Info,Type}' = 'media' then '[media]'
          else null
        end as preview_text
      from message_versions
      where message_id = m.id
      order by version_no desc
      limit 1
    ) mv on true
    where ($1::text is null or m.provider_group_id = $1::text)
      and not (
        -- Hide WhatsApp system/internal messages that carry no user-visible text
        -- (e.g. sender key distribution, protocol/app-state sync) unless they have media.
        mv.preview_text is null
        and not exists (select 1 from media_assets ma2 where ma2.message_id = m.id)
        and coalesce(mv.is_deleted, false) = false
        and (
          (mv.raw_event->'Message') ? 'senderKeyDistributionMessage'
          or (mv.raw_event->'Message') ? 'protocolMessage'
        )
      )
    order by m.created_at desc
    `,
    [providerGroupId ?? null],
  );

  return rows.map((row) => ({
    id: row.id,
    providerGroupId: row.provider_group_id,
    sender: row.sender_provider_user_id ?? "unknown",
    senderPhone: row.sender_phone ?? undefined,
    senderPushName: row.sender_pushname ?? undefined,
    preview: row.preview ?? "(no text)",
    hasMedia: row.has_media,
    isDeleted: Boolean(row.is_deleted),
    latestVersionNo: row.latest_version_no,
    createdAt: row.created_at,
  }));
}

type DbMessageVersionRow = {
  id: string;
  message_id: string;
  version_no: number;
  event_type: string;
  text_content: string | null;
  occurred_at: string;
};

function mapMessageEvent(eventType: string): MessageVersion["eventType"] {
  if (eventType.includes("edited")) return "edited";
  if (eventType.includes("deleted")) return "deleted";
  return "created";
}

export async function fetchMessageVersions(messageId: string): Promise<MessageVersion[]> {
  const rows = await dbQuery<DbMessageVersionRow>(
    `
    select
      id::text,
      message_id::text,
      version_no,
      event_type::text,
      text_content,
      occurred_at::text
    from message_versions
    where message_id = $1::uuid
    order by version_no desc
    `,
    [messageId],
  );

  return rows.map((row) => ({
    id: row.id,
    messageId: row.message_id,
    versionNo: row.version_no,
    eventType: mapMessageEvent(row.event_type),
    text: row.text_content ?? "",
    occurredAt: row.occurred_at,
  }));
}

type DbMediaRow = {
  id: string;
  message_id: string;
  mime_type: string;
  file_name: string | null;
  status: string;
  transcript: string | null;
  s3_key: string | null;
  metadata_json: Record<string, unknown> | null;
};

function mimeToKind(mimeType: string): MediaAsset["kind"] {
  const normalized = mimeType.toLowerCase();
  if (normalized.startsWith("image/") || normalized.endsWith("/image")) return "image";
  if (normalized.startsWith("audio/") || normalized.endsWith("/audio")) return "audio";
  if (normalized.startsWith("video/") || normalized.endsWith("/video")) return "video";
  return "file";
}

function resolveMediaPreviewUrl(row: DbMediaRow): string | undefined {
  const normalized = row.mime_type.toLowerCase();
  if (!(normalized.startsWith("image/") || normalized.endsWith("/image"))) {
    return undefined;
  }

  const metadata = row.metadata_json ?? {};
  const urlKeys = [
    "preview_url",
    "previewUrl",
    "public_url",
    "publicUrl",
    "object_url",
    "objectUrl",
    "download_url",
    "downloadUrl",
    "source_download_url",
    "sourceDownloadUrl",
    "url",
  ];

  for (const key of urlKeys) {
    const value = metadata[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }

  const publicBaseUrl =
    process.env.NEXT_PUBLIC_S3_PUBLIC_BASE_URL ?? process.env.S3_PUBLIC_BASE_URL;

  if (publicBaseUrl && row.s3_key) {
    const normalizedBase = publicBaseUrl.replace(/\/$/, "");
    const normalizedKey = row.s3_key.replace(/^\//, "");
    return `${normalizedBase}/${normalizedKey}`;
  }

  return undefined;
}

export async function fetchMediaAssets(messageId: string): Promise<MediaAsset[]> {
  const rows = await dbQuery<DbMediaRow>(
    `
    select
      ma.id::text,
      ma.message_id::text,
      ma.mime_type,
      ma.file_name,
      ma.status::text,
      ma.s3_key,
      ma.metadata_json,
      t.text_content as transcript
    from media_assets ma
    left join transcripts t on t.media_asset_id = ma.id
    where ma.message_id = $1::uuid
    order by ma.created_at asc
    `,
    [messageId],
  );

  return rows.map((row) => ({
    id: row.id,
    messageId: row.message_id,
    kind: mimeToKind(row.mime_type),
    filename: row.file_name ?? "attachment",
    status: toWorkflowStatus(row.status === "pending" ? "queued" : row.status),
    transcript: row.transcript ?? undefined,
    previewUrl: resolveMediaPreviewUrl(row),
  }));
}


type DbAuditRow = {
  id: string;
  event_type: string;
  actor: string | null;
  entity_type: string;
  entity_id: string;
  created_at: string;
  payload: Record<string, unknown> | null;
};

export async function fetchAuditEvents(): Promise<AuditEvent[]> {
  const rows = await dbQuery<DbAuditRow>(
    `
    select
      ae.id::text,
      ae.event_type,
      u.email as actor,
      ae.entity_type,
      ae.entity_id,
      ae.created_at::text,
      ae.payload
    from audit_events ae
    left join users u on u.id = ae.actor_user_id
    order by ae.created_at desc
    limit 200
    `,
  );

  return rows.map((row) => {
    const traceId =
      (row.payload?.trace_id as string | undefined) ??
      (row.payload?.traceId as string | undefined) ??
      row.id;

    return {
      id: row.id,
      eventType: row.event_type,
      actor: row.actor ?? "system",
      entityType: row.entity_type,
      entityId: row.entity_id,
      traceId,
      createdAt: row.created_at,
      metadata: row.payload ? JSON.stringify(row.payload) : "{}",
    };
  });
}

export async function fetchTraceDetail(traceId: string): Promise<TraceDetail | undefined> {
  const rows = await dbQuery<DbAuditRow>(
    `
    select
      ae.id::text,
      ae.event_type,
      u.email as actor,
      ae.entity_type,
      ae.entity_id,
      ae.created_at::text,
      ae.payload
    from audit_events ae
    left join users u on u.id = ae.actor_user_id
    where coalesce(ae.payload->>'trace_id', ae.payload->>'traceId') = $1
    order by ae.created_at desc
    limit 1
    `,
    [traceId],
  );

  const row = rows[0];
  if (!row) {
    return undefined;
  }

  return {
    traceId,
    providerGroupId:
      (row.payload?.provider_group_id as string | undefined) ??
      (row.payload?.providerGroupId as string | undefined) ??
      "unknown",
    inboundEventId:
      (row.payload?.inbound_event_id as string | undefined) ??
      (row.payload?.inboundEventId as string | undefined) ??
      row.id,
    retrievalRefs: Array.isArray(row.payload?.retrieval_refs)
      ? (row.payload?.retrieval_refs as string[])
      : [],
    modelPath: Array.isArray(row.payload?.model_path)
      ? (row.payload?.model_path as string[])
      : [],
    outboundIntentId:
      (row.payload?.outbound_intent_id as string | undefined) ??
      (row.payload?.outboundIntentId as string | undefined) ??
      "unknown",
  };
}

export async function fetchPromptAssets(instanceId?: string): Promise<PromptAsset[]> {
  const rows = await dbQuery<
    {
      binding_id: string;
      provider_group_id: string;
      template_id: string;
      template_name: string;
      template_version_id: string;
      version_no: number;
      status: string;
      updated_at: string;
      system_prompt: string | null;
    }
  >(
    `
    select
      gb.id::text as binding_id,
      gb.provider_group_id,
      gt.id::text as template_id,
      gt.display_name as template_name,
      tv.id::text as template_version_id,
      tv.version_no,
      tv.status::text,
      tv.updated_at::text,
      tv.system_prompt
    from group_bindings gb
    join template_versions tv on tv.id = gb.template_version_id
    join group_templates gt on gt.id = tv.template_id
    where ($1::text is null or gb.id::text = $1::text)
    order by gt.display_name asc, gb.updated_at desc
    `,
    [instanceId ?? null],
  );

  return rows.flatMap((row) => {
    const base: PromptAsset[] = [
      {
        id: `system-${row.template_version_id}`,
        templateId: row.template_id,
        templateName: row.template_name,
        templateVersionId: row.template_version_id,
        instanceId: row.binding_id,
        instanceName: titleFromGroupId(row.provider_group_id),
        type: "system",
        title: "System Prompt",
        status: toWorkflowStatus(row.status),
        versionNo: row.version_no,
        updatedAt: row.updated_at,
        updatedBy: "system",
      },
      {
        id: `user-${row.template_version_id}`,
        templateId: row.template_id,
        templateName: row.template_name,
        templateVersionId: row.template_version_id,
        instanceId: row.binding_id,
        instanceName: titleFromGroupId(row.provider_group_id),
        type: "user",
        title: "USER.md",
        status: toWorkflowStatus(row.status),
        versionNo: row.version_no,
        updatedAt: row.updated_at,
        updatedBy: "system",
      },
    ];

    return base;
  });
}
