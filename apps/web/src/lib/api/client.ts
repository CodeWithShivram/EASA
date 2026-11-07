import type { z } from "zod";

import { apiErrorBodySchema } from "./schemas";

export const CORRELATION_ID_HEADER = "X-Correlation-ID";
const DEFAULT_TIMEOUT_MS = 5000;

export type ApiErrorKind = "network" | "timeout" | "http" | "invalid_response";

/** Every failure of an API call is surfaced as an ApiError (except caller aborts). */
export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly correlationId: string | null;

  constructor(
    kind: ApiErrorKind,
    message: string,
    details: {
      status?: number;
      code?: string;
      correlationId?: string | null;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: details.cause });
    this.kind = kind;
    this.status = details.status ?? null;
    this.code = details.code ?? null;
    this.correlationId = details.correlationId ?? null;
  }
}

export interface ApiResult<T> {
  data: T;
  status: number;
  correlationId: string | null;
}

export interface ApiGetOptions<T> {
  /** Every successful (and accepted non-2xx) body is validated against this schema. */
  schema: z.ZodType<T>;
  /** Non-2xx statuses whose body is a valid response rather than an error (e.g. 503 readiness). */
  acceptStatuses?: readonly number[];
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

export async function apiGet<T>(
  baseUrl: string,
  path: string,
  options: ApiGetOptions<T>,
): Promise<ApiResult<T>> {
  const { schema, acceptStatuses = [], timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;
  const fetchImpl = options.fetchImpl ?? fetch;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", forwardAbort, { once: true });

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError("timeout", "The API did not respond in time.", { cause: error });
    }
    if (signal?.aborted) {
      throw error; // Cancelled by the caller; not an API failure.
    }
    throw new ApiError("network", "Cannot reach the API.", { cause: error });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }

  const correlationId = response.headers.get(CORRELATION_ID_HEADER);
  const body = await readJson(response, correlationId);

  if (response.ok || acceptStatuses.includes(response.status)) {
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new ApiError("invalid_response", "The API returned an unexpected response.", {
        status: response.status,
        correlationId,
        cause: parsed.error,
      });
    }
    return { data: parsed.data, status: response.status, correlationId };
  }

  const errorBody = apiErrorBodySchema.safeParse(body);
  if (errorBody.success) {
    const { code, message, correlation_id } = errorBody.data.error;
    throw new ApiError("http", message, {
      status: response.status,
      code,
      correlationId: correlation_id ?? correlationId,
    });
  }
  throw new ApiError("http", `The API request failed with status ${response.status}.`, {
    status: response.status,
    correlationId,
  });
}

async function readJson(response: Response, correlationId: string | null): Promise<unknown> {
  const text = await response.text();
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new ApiError("invalid_response", "The API returned an unexpected response.", {
      status: response.status,
      correlationId,
      cause: error,
    });
  }
}
