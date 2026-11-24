export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly codes: string[] = [],
    public readonly jobId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Library reads cross the shared library mount and can queue behind cover
// requests, so they get longer than ordinary calls before giving up.
export const LIBRARY_TIMEOUT = 20_000;

export async function api<T>(
  path: string,
  init: RequestInit & { timeout?: number } = {},
): Promise<T> {
  const { timeout = 5000, ...request } = init;
  const response = await fetch(`/api/${path}`, {
    ...request,
    signal: AbortSignal.any([
      ...(request.signal ? [request.signal] : []),
      AbortSignal.timeout(timeout),
    ]),
    headers: { "Content-Type": "application/json", ...request.headers },
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ error: `Request failed (${response.status})` }));
    throw new ApiError(
      body.error || `Request failed (${response.status})`,
      response.status,
      typeof body.code === "string" ? body.code : undefined,
      Array.isArray(body.codes)
        ? body.codes.filter((code: unknown) => typeof code === "string")
        : [],
      typeof body.job_id === "string" ? body.job_id : undefined,
    );
  }
  return response.json() as Promise<T>;
}
