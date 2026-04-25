import { NextResponse } from "next/server";

import { authenticateUser, ensureRequiredAdminAccount } from "@/lib/db/auth-repository";
import { isMissingRelationError } from "@/lib/db/postgres";
import { setSessionCookie } from "@/lib/auth/session";

function redirect303(request: Request, path: string): Response {
  return NextResponse.redirect(new URL(path, request.url), 303);
}

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");

  if (!email || !password) {
    return redirect303(request, "/login?error=missing");
  }

  try {
    await ensureRequiredAdminAccount();

    const user = await authenticateUser(email, password);
    if (!user) {
      return redirect303(request, "/login?error=invalid");
    }

    if (!user.isActive) {
      return redirect303(request, "/locked?reason=inactive");
    }

    await setSessionCookie({
      userId: user.userId,
      email: user.email,
      displayName: user.displayName,
      role: user.role,
      assignedGroupIds: user.assignedGroupIds,
      mustChangePassword: user.mustChangePassword,
    });

    if (user.mustChangePassword) {
      return redirect303(request, "/first-password-change");
    }

    return redirect303(request, "/overview");
  } catch (error) {
    console.error("[dashboard-auth] login failed", error);
    if (isMissingRelationError(error)) {
      return redirect303(request, "/login?error=schema-missing");
    }
    return redirect303(request, "/login?error=db");
  }
}

