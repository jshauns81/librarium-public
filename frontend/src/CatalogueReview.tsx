import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { intentKey, mergeJobs } from "./state";
import { JobProgress } from "./JobProgress";
import type { Job } from "./types";

const active = (job: Job) => ["queued", "running"].includes(job.state);

export function CatalogueReview({
  workId,
  title,
  version,
  sha256,
  fixture,
}: {
  workId: string;
  title: string;
  version: string;
  sha256: string;
  fixture: boolean;
}) {
  const client = useQueryClient();
  const [notice, setNotice] = useState("");
  const [refreshRequest, setRefreshRequest] = useState<{
    scope: string;
  } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const scope = `catalogue:${workId}:${version}:${sha256}`;
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const queryKey = ["catalogue-reviews", workId];
  const session = useQuery({
    queryKey: ["session"],
    queryFn: ({ signal }) => api<{ csrf: string }>("session", { signal }),
    staleTime: Infinity,
    retry: false,
  });
  const jobs = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      api<{ jobs: Job[] }>(
        `jobs?${new URLSearchParams({ kind: "catalogue", work_id: workId })}`,
        { signal },
      ),
    retry: false,
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.status < 500
        ? false
        : 1500,
    structuralSharing: (old, incoming) => ({
      jobs: mergeJobs(
        (old as { jobs: Job[] } | undefined)?.jobs ?? [],
        (incoming as { jobs: Job[] }).jobs,
      ),
    }),
  });
  const refreshing = refreshRequest?.scope === scope;
  async function refresh() {
    const request = { scope };
    setRefreshRequest(request);
    try {
      await jobs.refetch();
    } finally {
      setRefreshRequest((current) => (current === request ? null : current));
    }
  }
  const records = (jobs.data?.jobs ?? [])
    .filter((job) => job.work_id === workId && job.kind === "catalogue")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const job = records.find(active) ?? records[0];
  function remember(value: Job) {
    client.setQueryData<{ jobs: Job[] }>(
      ["catalogue-reviews", value.work_id],
      (old) => ({ jobs: mergeJobs(old?.jobs ?? [], [value]) }),
    );
    for (const [key] of client.getQueriesData({ queryKey: ["jobs"] })) {
      if (key[2] === "synthetic") continue;
      client.setQueryData<{ jobs: Job[] }>(key, (old) => ({
        jobs: mergeJobs(old?.jobs ?? [], [value]),
      }));
    }
    void client.invalidateQueries({ queryKey: ["jobs"] });
  }
  function clearIntent(value: Job) {
    const name = `librarium-intent:catalogue:${value.work_id}:${value.source_version}:${value.source_sha256}`;
    if (localStorage.getItem(name) === value.request_key)
      localStorage.removeItem(name);
  }
  function restoreFocus(
    context: { element: Element | null; scope: string } | undefined,
  ) {
    if (context?.scope !== currentScope.current) return;
    if (context.element && document.activeElement === document.body)
      heading.current?.focus({ preventScroll: true });
  }
  const start = useMutation({
    onMutate: (request: {
      scope: string;
      workId: string;
      version: string;
      sha256: string;
      requestKey: string;
    }) => ({ ...request, element: document.activeElement }),
    mutationFn: async (request: {
      scope: string;
      workId: string;
      version: string;
      sha256: string;
      requestKey: string;
    }) => {
      if (!session.data) throw new Error("Connection is not ready.");
      return api<Job>("jobs", {
        method: "POST",
        headers: {
          "X-CSRFToken": session.data.csrf,
          "Idempotency-Key": request.requestKey,
        },
        body: JSON.stringify({
          catalogue_work_id: request.workId,
          version: request.version,
          sha256: request.sha256,
        }),
      });
    },
    onSuccess: (value, _variables, context) => {
      remember(value);
      clearIntent(value);
      if (context.scope === currentScope.current)
        setNotice(active(value) ? "Review saved." : "Saved review available.");
    },
    onError: (error, _variables, context) => {
      const confirmed =
        context &&
        client
          .getQueryData<{ jobs: Job[] }>(["catalogue-reviews", context.workId])
          ?.jobs.find(
            (value) =>
              value.kind === "catalogue" &&
              value.work_id === context.workId &&
              value.request_key === context.requestKey,
          );
      if (confirmed && context.scope === currentScope.current) {
        start.reset();
        setNotice("Review confirmed.");
      } else if (context?.scope === currentScope.current)
        setNotice(
          error instanceof ApiError && error.status < 500
            ? error.message
            : "Review unconfirmed. Retry or refresh.",
        );
      void jobs.refetch();
    },
    onSettled: (_data, _error, _variables, context) => restoreFocus(context),
  });
  const cancel = useMutation({
    onMutate: () => ({ scope, element: document.activeElement }),
    mutationFn: (value: Job) =>
      api<Job>(`jobs/${value.id}`, {
        method: "POST",
        headers: { "X-CSRFToken": session.data!.csrf },
        body: "{}",
      }),
    onSuccess: (value, _variables, context) => {
      remember(value);
      if (context.scope === currentScope.current)
        setNotice(
          value.state === "cancelled"
            ? "Review cancelled."
            : active(value)
              ? "Cancellation unconfirmed. Refresh."
              : "Review already finished.",
        );
    },
    onError: (_error, _variables, context) => {
      if (context?.scope === currentScope.current)
        setNotice("Cancellation unconfirmed. Retry or refresh.");
    },
    onSettled: (_data, _error, _variables, context) => restoreFocus(context),
  });
  useEffect(() => {
    setNotice("");
    start.reset();
    cancel.reset();
  }, [scope]);
  useEffect(() => {
    const saved = records.find(
      (value) =>
        value.request_key === localStorage.getItem(`librarium-intent:${scope}`),
    );
    if (saved) {
      clearIntent(saved);
      if (start.isError) {
        start.reset();
        setNotice("Review confirmed.");
      }
    }
  }, [jobs.data, scope]);
  return (
    <section
      className="detail-section catalogue-review"
      aria-label={`Catalogue metadata review for ${title}`}
    >
      <h3 ref={heading} tabIndex={-1}>
        Catalogue metadata review
      </h3>
      <p>Metadata only. Books unchanged.</p>
      {fixture && <p className="context-note">Fixture data.</p>}
      <div className="review-actions">
        <button
          className="secondary"
          disabled={
            !session.data ||
            jobs.isPending ||
            jobs.isError ||
            start.isPending ||
            (!!job && active(job))
          }
          onClick={() =>
            start.mutate({
              scope,
              workId,
              version,
              sha256,
              requestKey: intentKey(localStorage, scope),
            })
          }
        >
          {start.isPending
            ? "Saving review…"
            : job?.state === "failed" &&
                job.source_version === version &&
                job.source_sha256 === sha256
              ? "Retry catalogue review"
              : "Review catalogue metadata"}
        </button>
        <button
          aria-label="Refresh review progress"
          aria-busy={refreshing}
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
        {job && active(job) && (
          <button
            className="cancel"
            disabled={!session.data || cancel.isPending}
            onClick={() => cancel.mutate(job)}
          >
            {cancel.isPending ? "Cancelling…" : "Cancel review"}
          </button>
        )}
      </div>
      {session.error && (
        <p className="error" role="alert">
          Review connection unavailable.{" "}
          <button onClick={() => void session.refetch()}>
            Retry review connection
          </button>
        </p>
      )}
      {jobs.error && (
        <p className="error" role="alert">
          Progress unavailable. Saved results may be stale. {jobs.error.message}
        </p>
      )}
      <p className="announcement" role="status">
        {notice}
      </p>
      {job && (
        <>
          {(job.source_version !== version || job.source_sha256 !== sha256) && (
            <p className="context-note">
              Saved review uses snapshot {job.source_version}.
            </p>
          )}
          <JobProgress
            job={job}
            announce={
              job.source_version === version && job.source_sha256 === sha256
            }
          />
        </>
      )}
    </section>
  );
}
