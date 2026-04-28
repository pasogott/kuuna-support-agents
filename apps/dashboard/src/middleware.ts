import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Do not use `0.0.0.0` in the browser bar — cookies/session are unreliable.
 * Redirect only when the *client* Host is literally 0.0.0.0.
 *
 * Important: use the `Host` header (actual client target), not `nextUrl.hostname`.
 * In Docker, `nextUrl` can look like 0.0.0.0 (bind address) even when the user
 * opened http://127.0.0.1:3000, which would cause a redirect loop.
 */
export function middleware(request: NextRequest) {
  const hostHeader = request.headers.get("host");
  let hostname: string;
  if (hostHeader) {
    try {
      const u = new URL(`http://${hostHeader}`);
      hostname = u.hostname;
    } catch {
      return NextResponse.next();
    }
  } else {
    hostname = request.nextUrl.hostname;
  }

  if (hostname !== "0.0.0.0") {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.hostname = "127.0.0.1";
  return NextResponse.redirect(url, 307);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)).*)"],
};
