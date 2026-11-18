import type { z } from "zod";

import { ApiError, CORRELATION_ID_HEADER, type ApiResult } from "./client";
import { apiErrorBodySchema } from "./schemas";

/**
 * Requests from the browser to this app's backend for frontend (`/bff/...`).
 * The session cookie is sent automatically (same origin) and is never
 * readable by scripts; the server adds the API token.
 */

export const BFF_API = "/bff/api/v1";
const DEFAULT_TIMEOUT_MS = 30_000;

export interface BffRequestOptions<T> {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  /** Sent as JSON. */
  json?: unknown;
  /** Sent as multipart form data (uploads). */
  formData?: FormData;
  /** Validates the response body; omit for responses without a body (204). */
  schema?: z.ZodType<T>;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

export async function bffRequest<T = undefined>(
  path: string,
  options: BffRequestOptions<T> = {},
): Promise<ApiResult<T>> {
  const {
    method = "GET",
    json,
    formData,
    schema,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal,
  } = options;
  const fetchImpl = options.fetchImpl ?? fetch;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", forwardAbort, { once: true });

  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (formData) {
    body = formData; // the browser sets the multipart boundary
  }

  let response: Response;
  try {
    response = await fetchImpl(path, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut)
      throw new ApiError("timeout", "The request took too long.", {
        cause: error,
      });
    if (signal?.aborted) throw error;
    throw new ApiError("network", "Cannot reach the EASA web server.", {
      cause: error,
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }

  const correlationId = response.headers.get(CORRELATION_ID_HEADER);
  const text = await response.text();
  let parsedBody: unknown = undefined;
  if (text) {
    try {
      parsedBody = JSON.parse(text) as unknown;
    } catch (error) {
      throw new ApiError("invalid_response", "The server returned an unexpected response.", {
        status: response.status,
        correlationId,
        cause: error,
      });
    }
  }

  if (response.ok) {
    if (!schema) return { data: undefined as T, status: response.status, correlationId };
    const parsed = schema.safeParse(parsedBody);
    if (!parsed.success) {
      throw new ApiError("invalid_response", "The server returned an unexpected response.", {
        status: response.status,
        correlationId,
        cause: parsed.error,
      });
    }
    return { data: parsed.data, status: response.status, correlationId };
  }

  const errorBody = apiErrorBodySchema.safeParse(parsedBody);
  if (errorBody.success) {
    const { code, message, correlation_id } = errorBody.data.error;
    throw new ApiError("http", message, {
      status: response.status,
      code,
      correlationId: correlation_id ?? correlationId,
    });
  }
  throw new ApiError("http", `The request failed with status ${response.status}.`, {
    status: response.status,
    correlationId,
  });
}
