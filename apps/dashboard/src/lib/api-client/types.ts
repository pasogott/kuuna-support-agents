export type WorkflowStatus =
  | "draft"
  | "ready"
  | "published"
  | "archived"
  | "active"
  | "inactive"
  | "provisioning"
  | "failed"
  | "queued"
  | "processing"
  | "running"
  | "succeeded"
  | "cancelled";

export type TemplateBuildStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type GroupTemplate = {
  id: string;
  key: string;
  displayName: string;
  description: string;
  publishedVersionId: string;
  updatedAt: string;
};

export type TemplateVersion = {
  id: string;
  templateId: string;
  versionNo: number;
  status: WorkflowStatus;
  systemPrompt?: string;
  modelChain: string[];
  allowedTools?: string[];
  toolProfile: string;
  egressPolicy: string;
  updatedAt: string;
  updatedBy: string;
};

export type TemplateBuild = {
  id: string;
  templateId: string;
  templateVersionId: string;
  status: TemplateBuildStatus;
  imageRef?: string;
  imageTag?: string;
  buildInputs: Record<string, unknown>;
  logsRef?: string;
  createdAt: string;
  updatedAt: string;
};

export type GroupBinding = {
  id: string;
  providerGroupId: string;
  groupTitle: string;
  templateVersionId: string;
  status: WorkflowStatus;
  runtimeMode: "on-demand" | "hot";
  updatedAt: string;
};

export type ToolCatalogItem = {
  id: string;
  toolKey: string;
  displayName: string;
  description: string;
  riskClass: "read" | "write" | "admin";
  category: string;
  isEnabled: boolean;
  updatedAt: string;
};

export type KnownProviderGroup = {
  providerGroupId: string;
  groupTitle: string;
  lastSeenAt?: string;
  sources: Array<"binding" | "message" | "assignment" | "knowledge">;
};

export type BindingTimelineEvent = {
  id: string;
  bindingId: string;
  status: WorkflowStatus;
  label: string;
  occurredAt: string;
  details?: string;
};

export type PromptAsset = {
  id: string;
  templateId: string;
  templateName: string;
  templateVersionId: string;
  instanceId: string;
  instanceName: string;
  type: "system" | "user";
  title: string;
  status: WorkflowStatus;
  versionNo: number;
  updatedAt: string;
  updatedBy: string;
};

export type RuntimeRunStatus = "started" | "succeeded" | "failed" | "timeout";

export type RuntimeRun = {
  id: string;
  providerGroupId: string;
  messageId?: string;
  bindingId: string;
  templateVersionId: string;
  templateBuildId?: string;
  imageRef: string;
  status: RuntimeRunStatus;
  startedAt: string;
  finishedAt?: string;
  durationMs?: number;
  error?: string;
  execution: Record<string, unknown>;
};

export type KnowledgeDoc = {
  id: string;
  docKey: string;
  scope: "common" | "group";
  providerGroupId?: string;
  title: string;
  status: WorkflowStatus;
  updatedAt: string;
  updatedBy: string;
  chunkCount: number;
};

export type KnowledgeDocVersion = {
  id: string;
  scope: "common" | "group";
  docRefId: string;
  versionNo: number;
  status: WorkflowStatus;
  contentMarkdown: string;
  createdAt: string;
  updatedAt: string;
  updatedBy: string;
};

export type MessageRecord = {
  id: string;
  providerGroupId: string;
  sender: string;
  senderPhone?: string;
  senderPushName?: string;
  preview: string;
  hasMedia: boolean;
  isDeleted: boolean;
  latestVersionNo: number;
  createdAt: string;
};

export type MessageVersion = {
  id: string;
  messageId: string;
  versionNo: number;
  eventType: "created" | "edited" | "deleted";
  text: string;
  occurredAt: string;
};

export type MediaAsset = {
  id: string;
  messageId: string;
  kind: "image" | "audio" | "video" | "file";
  filename: string;
  status: WorkflowStatus;
  transcript?: string;
  previewUrl?: string;
};

export type AuditEvent = {
  id: string;
  eventType: string;
  actor: string;
  entityType: string;
  entityId: string;
  traceId: string;
  createdAt: string;
  metadata: string;
};

export type TraceDetail = {
  traceId: string;
  providerGroupId: string;
  inboundEventId: string;
  retrievalRefs: string[];
  modelPath: string[];
  outboundIntentId: string;
};

export type StaffUser = {
  id: string;
  email: string;
  displayName: string;
  role: "owner" | "admin" | "operator" | "viewer";
  active: boolean;
};

export type GroupAssignment = {
  id: string;
  userId: string;
  user: string;
  providerGroupId: string;
  groupTitle: string;
};

export type RuntimeDebugStatus = {
  runtimeHealth: "ok" | "unreachable" | "error";
  runtimeUrl?: string;
  openaiConfigured: boolean | null;
  openaiBaseUrl?: string;
  openaiTimeoutSeconds?: string;
  lastModelPath: string[];
  lastModelUsed?: string;
  lastOutboundIntentId?: string;
  lastOutboundAt?: string;
  error?: string;
};
