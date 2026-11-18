import { NextResponse, type NextRequest } from "next/server";

import {
  CORRELATION_ID_HEADER,
  MAX_BODY_BYTES,
  SLOW_TIMEOUT_MS,
  TIMEOUT_MS,
  callApi,
  clearSessionCookie,
  errorResponse,
  isSameOrigin,
  sessionToken,
  unavailable,
} from "@/lib/server/bff";
import { findRoute } from "@/lib/server/routes";

/**
 * Forwards allowlisted requests to the API with the session's bearer token
 * (Phase 7, ADR-034). Only the method, the path, the query string (GET), the
 * body and its content type are forwarded; the browser's cookies and any
 * Authorization header it sends are not.
 */

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: Context): Promise<NextResponse> {
  const { path } = await context.params;
  // Segments arrive decoded: refuse anything that could change the path's meaning.
  if (path.some((s) => s === "" || s === "." || s === ".." || /[\\/?#%]/.test(s))) {
    return errorResponse(404, "not_found", "Not found.");
  }
  const apiPath = `/${path.join("/")}`;
  const route = findRoute(request.method, apiPath);
  if (!route) return errorResponse(404, "not_found", "Not found.");
  if (request.method !== "GET" && !isSameOrigin(request)) {
    return errorResponse(403, "bad_origin", "This request must come from the EASA web app.");
  }
  const token = sessionToken(request);
  if (!route.public && !token) {
    return errorResponse(401, "not_authenticated", "Authentication required.");
  }

  const headers: Record<string, string> = {};
  if (token && !route.public) headers.Authorization = `Bearer ${token}`;
  let body: ArrayBuffer | undefined;
  if (request.method === "POST" || request.method === "PATCH") {
    const declared = Number(request.headers.get("content-length") ?? 0);
    if (declared > MAX_BODY_BYTES) {
      return errorResponse(413, "request_too_large", "The request is too large.");
    }
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return errorResponse(413, "request_too_large", "The request is too large.");
    }
    const contentType = request.headers.get("content-type");
    if (contentType) headers["Content-Type"] = contentType;
  }
  const query = request.method === "GET" ? request.nextUrl.search : "";

  let api: Response;
  try {
    api = await callApi(`${apiPath}${query}`, {
      method: request.method,
      headers,
      body,
      timeoutMs: route.slow ? SLOW_TIMEOUT_MS : TIMEOUT_MS,
    });
  } catch (error) {
    return unavailable(error);
  }

  const response = new NextResponse(api.status === 204 ? null : await api.arrayBuffer(), {
    status: api.status,
  });
  for (const name of ["content-type", CORRELATION_ID_HEADER]) {
    const value = api.headers.get(name);
    if (value) response.headers.set(name, value);
  }
  // The API no longer accepts this token (expired, revoked, user disabled).
  if (api.status === 401 && token) clearSessionCookie(response, request);
  return response;
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
