import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/server/bff";

/**
 * Optimistic check only (Phase 7): pages without a session cookie go to the
 * sign-in page. Whether a session is valid, and what it may do, is decided by
 * the API on every request, never here.
 */
export function proxy(request: NextRequest): NextResponse {
  if (!request.cookies.get(SESSION_COOKIE)?.value) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the sign-in page, the backend-for-frontend routes and static files.
  matcher: ["/((?!login|bff|_next/static|_next/image|favicon.ico).*)"],
};
