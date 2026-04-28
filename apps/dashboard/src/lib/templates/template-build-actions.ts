"use server";

import { redirect } from "next/navigation";
import { isRedirectError } from "next/dist/client/components/redirect-error";

import { requireAuthorized } from "@/lib/auth/guards";

type InternalTemplateBuildResponse = {
  id: string;
  template_id: string;
  template_version_id: string;
  status: string;
};

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

function getInternalOpsToken(): string | undefined {
  return process.env.DASHBOARD_INTERNAL_OPS_TOKEN ?? process.env.INTERNAL_OPS_TOKEN;
}

function parseCsvTools(raw: string | null): string[] | undefined {
  if (!raw) {
    return undefined;
  }

  const items = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return items.length ? items : undefined;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}

export async function queueTemplateBuildAction(formData: FormData): Promise<void> {
  const session = await requireAuthorized("templates", "publish");

  const internalToken = getInternalOpsToken();
  if (!internalToken) {
    redirect(
      `/templates/${encodeURIComponent(String(formData.get("templateId") ?? ""))}?error=${encodeURIComponent("Template-Builds: INTERNAL_OPS_TOKEN fehlt")}`,
    );
  }

  const templateIdRaw = formData.get("templateId");
  const versionIdRaw = formData.get("versionId");
  const baseImageRaw = formData.get("baseImage");
  const allowedToolsRaw = formData.get("allowedTools");

  const templateId = typeof templateIdRaw === "string" ? templateIdRaw.trim() : "";
  const versionId = typeof versionIdRaw === "string" ? versionIdRaw.trim() : "";
  const baseImage = typeof baseImageRaw === "string" ? baseImageRaw.trim() : "";

  if (!templateId || !versionId || !baseImage) {
    redirect(
      `/templates/${encodeURIComponent(templateId || "unknown")}?error=${encodeURIComponent("Template-Builds: templateId, versionId und base_image sind erforderlich.")}`,
    );
  }

  if (!isUuid(session.userId)) {
    redirect(
      `/templates/${encodeURIComponent(templateId)}?error=${encodeURIComponent(
        "Template-Builds: session.userId ist keine UUID (legacy session). Bitte neu einloggen.",
      )}`,
    );
  }

  const payload = {
    actor_user_id: session.userId,
    base_image: baseImage,
    allowed_tools: parseCsvTools(typeof allowedToolsRaw === "string" ? allowedToolsRaw : null),
  };

  const path = `/internal/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(versionId)}/builds`;

  let lastError = "no-backend-url";

  for (const backendBaseUrl of BACKEND_URL_CANDIDATES) {
    try {
      const response = await fetch(`${backendBaseUrl.replace(/\/$/, "")}${path}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Internal-Token": internalToken,
        },
        body: JSON.stringify(payload),
        cache: "no-store",
      });

      if (!response.ok) {
        const body = await response.text();
        lastError = `${response.status}:${body}`;
        continue;
      }

      const data = (await response.json()) as InternalTemplateBuildResponse;
      const params = new URLSearchParams({
        buildQueued: "1",
        buildId: data.id,
        versionId: data.template_version_id,
      });

      redirect(`/templates/${encodeURIComponent(templateId)}?${params.toString()}`);
    } catch (error) {
      if (isRedirectError(error)) {
        throw error;
      }
      lastError = error instanceof Error ? error.message : String(error);
    }
  }

  redirect(
    `/templates/${encodeURIComponent(templateId)}?error=${encodeURIComponent(`Template-Builds: ${lastError}`)}`,
  );
}
