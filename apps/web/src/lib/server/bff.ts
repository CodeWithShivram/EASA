import { NextResponse, type NextRequest } from "next/server";

import { serverConfig } from "@/lib/config";

/**
 * Backend-for-frontend helpers (Phase 7, ADR-034). The API session token lives
 * only in an HttpOnly, SameSite=Strict cookie that page scripts cannot read;
 * these route handlers add it as a bearer token when calling the API.
 */

export const SESSION_COOKIE = "easa_session";
export const CORRELATION_ID_HEADER = "X-Correlation-ID";
// The API's upload limit (10 MiB) plus multipart overhead; larger bodies are refused here.
export const MAX_BODY_BYTES = 10 * 1024 * 1024 + 64 * 1024;
export const TIMEOUT_MS = 30_000;
export const SLOW_TIMEOUT_MS = 330_000;

/** An error in the API's envelope shape, so the browser handles both the same way. */
export function errorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message, correlation_id: null } }, { status });
}

/**
 * Requests that change something must come from this app's own pages. With
 * SameSite=Strict cookies this blocks cross-site request forgery even in
 * browsers that send the cookie in unusual cases.
 *
 * The browser's Origin is compared with the host it addressed (the Host
 * header), not with request.nextUrl: a server listening on 0.0.0.0, as in the
 * container (P8-M5), reports that address there instead of the browser's.
 */
export function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host") ?? request.nextUrl.host;
  return origin !== null && origin === `${request.nextUrl.protocol}//${host}`;
}

export function sessionToken(request: NextRequest): string | undefined {
  return request.cookies.get(SESSION_COOKIE)?.value || undefined;
}

function secureCookies(request: NextRequest): boolean {
  return process.env.NODE_ENV === "production" || request.nextUrl.protocol === "https:";
}

export function setSessionCookie(
  response: NextResponse,
  request: NextRequest,
  token: string,
  expiresAt: Date,
): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: secureCookies(request),
    sameSite: "strict",
    path: "/",
    expires: expiresAt,
  });
}

export function clearSessionCookie(response: NextResponse, request: NextRequest): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    secure: secureCookies(request),
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
}

/** Call the API. Never follows redirects; never caches. */
export async function callApi(
  path: string,
  init: {
    method: string;
    headers?: Record<string, string>;
    body?: BodyInit;
    timeoutMs?: number;
  },
): Promise<Response> {
  const { apiUrl } = serverConfig();
  return fetch(`${apiUrl}/api/v1${path}`, {
    method: init.method,
    headers: { Accept: "application/json", ...init.headers },
    body: init.body,
    cache: "no-store",
    redirect: "manual",
    signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS),
  });
}

/** The API could not be reached or did not answer in time. */
export function unavailable(error: unknown): NextResponse {
  const timedOut = error instanceof DOMException && error.name === "TimeoutError";
  return timedOut
    ? errorResponse(504, "api_timeout", "The API did not respond in time.")
    : errorResponse(502, "api_unreachable", "Cannot reach the API.");
}
