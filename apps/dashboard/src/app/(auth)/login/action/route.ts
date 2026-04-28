import { NextResponse } from "next/server";

import { authenticateUser, ensureRequiredAdminAccount } from "@/lib/db/auth-repository";
import { isMissingRelationError } from "@/lib/db/postgres";
import { setSessionCookie } from "@/lib/auth/session";

/**
 * After a form POST, redirect must be **303 See Other** so the browser follows with **GET** (PRG).
 * NextResponse.redirect() defaults to **307**, which preserves POST and can yield POST /overview (405/odd behavior).
 */
function redirect303(path: string, request: Request): Response {
  return NextResponse.redirect(new URL(path, request.url), 303);
}

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");

  if (!email || !password) {
    return redirect303("/login?error=missing", request);
  }

  try {
    await ensureRequiredAdminAccount();

    const user = await authenticateUser(email, password);
    if (!user) {
      return redirect303("/login?error=invalid", request);
    }

    if (!user.isActive) {
      return redirect303("/locked?reason=inactive", request);
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
      return redirect303("/first-password-change", request);
    }

    return redirect303("/overview", request);
  } catch (error) {
    console.error("[dashboard-auth] login failed", error);
    if (isMissingRelationError(error)) {
      return redirect303("/login?error=schema-missing", request);
    }
    return redirect303("/login?error=db", request);
  }
}
