import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";

import {
  CORRELATION_ID_HEADER,
  callApi,
  clearSessionCookie,
  errorResponse,
  isSameOrigin,
  sessionToken,
  setSessionCookie,
  unavailable,
} from "@/lib/server/bff";

/**
 * Sign-in session of the browser (Phase 7, ADR-034).
 * POST signs in (the API token goes into the HttpOnly cookie, never into the
 * response body), GET returns the current user, DELETE signs out.
 */

const loginResponseSchema = z.object({
  token: z.string().min(1),
  expires_at: z.iso.datetime({ offset: true }),
  user: z.record(z.string(), z.unknown()),
});

function relay(api: Response, body: unknown): NextResponse {
  const response = NextResponse.json(body, { status: api.status });
  const correlationId = api.headers.get(CORRELATION_ID_HEADER);
  if (correlationId) response.headers.set(CORRELATION_ID_HEADER, correlationId);
  return response;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return {
      error: {
        code: "invalid_response",
        message: "The API returned an unexpected response.",
        correlation_id: null,
      },
    };
  }
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const token = sessionToken(request);
  if (!token) return errorResponse(401, "not_authenticated", "Authentication required.");
  let api: Response;
  try {
    api = await callApi("/auth/me", {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch (error) {
    return unavailable(error);
  }
  const response = relay(api, await readJson(api));
  if (api.status === 401) clearSessionCookie(response, request);
  return response;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOrigin(request)) {
    return errorResponse(403, "bad_origin", "This request must come from the EASA web app.");
  }
  let credentials: unknown;
  try {
    credentials = await request.json();
  } catch {
    return errorResponse(422, "invalid_request", "Send the username and password as JSON.");
  }
  let api: Response;
  try {
    // The browser's address as Next.js reports it. The API uses it for its sign-in
    // limit only if it trusts this server (EASA_TRUSTED_PROXIES), which is reliable
    // only behind a reverse proxy that overwrites X-Forwarded-For (ADR-035).
    const forwarded = request.headers.get("x-forwarded-for");
    api = await callApi("/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(forwarded ? { "X-Forwarded-For": forwarded } : {}),
      },
      body: JSON.stringify(credentials),
    });
  } catch (error) {
    return unavailable(error);
  }
  const body = await readJson(api);
  if (!api.ok) return relay(api, body);
  const parsed = loginResponseSchema.safeParse(body);
  if (!parsed.success) {
    return errorResponse(502, "invalid_response", "The API returned an unexpected response.");
  }
  // The token stays on the server side of the browser: only the user is returned.
  const response = relay(api, {
    user: parsed.data.user,
    expires_at: parsed.data.expires_at,
  });
  setSessionCookie(response, request, parsed.data.token, new Date(parsed.data.expires_at));
  return response;
}

export async function DELETE(request: NextRequest): Promise<NextResponse> {
  if (!isSameOrigin(request)) {
    return errorResponse(403, "bad_origin", "This request must come from the EASA web app.");
  }
  const token = sessionToken(request);
  if (token) {
    try {
      await callApi("/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // Signing out locally still works; the server session expires on its own.
    }
  }
  const response = new NextResponse(null, { status: 204 });
  clearSessionCookie(response, request);
  return response;
}
