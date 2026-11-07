import { apiGet, type ApiResult } from "./client";
import { readinessSchema, type Readiness } from "./schemas";

export interface RequestOptions {
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** GET /api/v1/health/ready. A 503 "not_ready" body is a valid result, not an error. */
export function getReadiness(
  baseUrl: string,
  options: RequestOptions = {},
): Promise<ApiResult<Readiness>> {
  return apiGet(baseUrl, "/api/v1/health/ready", {
    schema: readinessSchema,
    acceptStatuses: [503],
    ...options,
  });
}
