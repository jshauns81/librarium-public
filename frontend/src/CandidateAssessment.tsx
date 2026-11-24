import { useBookWorkspace } from "./book-workspace";
import React, { useEffect, useId, useRef, useState } from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { JobProgress } from "./JobProgress";
import type { Job, Session } from "./types";
import {
  assessmentJobBinds,
  clearAssessmentIntent,
  clearReconciliationIntent,
  extractAssessmentReport,
  fetchCandidateAssessmentHistory,
  fetchContentReferences,
  fetchDirectLibraryInventory,
  fetchReconciliationJobHistory,
  fetchSavedReconciliations,
  readAssessmentIntent,
  readReconciliationIntent,
  recoverCandidateAssessment,
  recoverReconciliationJob,
  requestCandidateAssessment,
  requestReconciliationJob,
  sameComparisonPins,
  sameReferencePin,
  ANY_UUID_PATTERN,
  DIGEST_PATTERN,
  saveAssessmentIntent,
  saveReconciliationIntent,
  type AssessmentIntent,
  type BookAssessmentReport,
  type CatalogueSnapshotPin,
  type ComparisonInspectionPin,
  type ReconciliationIntent,
  type ReferenceAuthenticationResult,
  type ReferenceSelectionPin,
  type SpineOverlapEvidence,
  type SavedReconciliationSummary,
} from "./candidate-assessment-api";
import "./candidate-assessment.css";

const active = (job?: Pick<Job, "state"> | null) =>
  !!job && ["queued", "running"].includes(job.state);
const newer = (left: Job | undefined, right: Job | undefined) =>
  left && right
    ? left.revision >= right.revision
      ? left
      : right
    : (left ?? right);

function distinctScope(scope: string, statement: string) {
  let remaining = scope.trim();
  while (remaining.startsWith(statement))
    remaining = remaining.slice(statement.length).trimStart();
  while (remaining.endsWith(statement))
    remaining = remaining.slice(0, -statement.length).trimEnd();
  return remaining;
}

function AssessmentPages({
  data,
  label,
  change,
}: {
  data?: { page: number; pages: number };
  label: string;
  change: (page: number) => void;
}) {
  if (!data || data.pages <= 1) return null;
  return (
    <nav className="pagination" aria-label={`${label} pages`}>
      <button
        type="button"
        disabled={data.page <= 1}
        onClick={() => change(data.page - 1)}
      >
        Previous {label} page
      </button>
      <span>
        Page {data.page} of {data.pages}
      </span>
      <button
        type="button"
        disabled={data.page >= data.pages}
        onClick={() => change(data.page + 1)}
      >
        Next {label} page
      </button>
    </nav>
  );
}

const relationLabels: Record<string, string> = {
  all_spine_resources_same: "All reading-order spine resources match",
  selected_spine_resources_contained:
    "Selected spine resources are contained in comparison",
  comparison_spine_resources_contained:
    "Comparison spine resources are contained in selected",
  shared_spine_resources: "Some reading-order spine resources are shared",
  no_shared_spine_resources: "No shared reading-order spine resources",
  all_document_text_same: "All reading-order document body text matches",
  selected_document_text_contained:
    "Selected document body text is contained in comparison",
  comparison_document_text_contained:
    "Comparison document body text is contained in selected",
  shared_document_text: "Some reading-order document body text is shared",
  no_shared_document_text: "No shared reading-order document body text",
  unconfirmed: "Unconfirmed",
};

const authStatusLabels: Record<string, string> = {
  not_requested: "Not requested",
  authenticated_reference_match: "Authenticated curated reference match",
  different_bytes: "Candidate bytes differ from curated reference",
  unconfirmed: "Unconfirmed",
};

function SpineOverlapSection({
  title,
  overlap,
}: {
  title: string;
  overlap: SpineOverlapEvidence | undefined;
}) {
  if (!overlap) return null;
  return (
    <div className="assessment-overlap">
      <p>
        <strong>{title}:</strong>{" "}
        {relationLabels[overlap.relation] ?? overlap.relation} ({overlap.status}
        )
      </p>
      <p className="context-note">
        Matched {overlap.matched_documents?.toLocaleString() ?? "unknown"} of{" "}
        {overlap.selected_documents ?? "unknown"} selected /{" "}
        {overlap.comparison_documents ?? "unknown"} comparison documents
        {overlap.pairing_order_preserved === true
          ? " · matched-pair order preserved"
          : overlap.pairing_order_preserved === false
            ? " · matched-pair order differs"
            : ""}
      </p>
      {overlap.matches.length > 0 && (
        <ul className="assessment-matches-list">
          {overlap.matches.map((match, idx) => (
            <li key={idx}>
              <span className="assessment-code">
                {match.selected.path} (#{match.selected.spine_index}) ↔{" "}
                {match.comparison.path} (#{match.comparison.spine_index})
              </span>
              {typeof match.text_chars === "number" && (
                <span> · {match.text_chars.toLocaleString()} chars</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="context-note">{overlap.limitations}</p>
      {overlap.truncated && (
        <p>
          Showing {overlap.matches.length} matched pairs; complete counts are
          recorded above.
        </p>
      )}
    </div>
  );
}

function ReferenceAuthenticationSection({
  auth,
  level = 5,
}: {
  auth: ReferenceAuthenticationResult | null | undefined;
  level?: 4 | 5;
}) {
  const Heading = level === 4 ? "h4" : "h5";
  if (!auth) {
    return (
      <div className="assessment-subsection">
        <Heading>Curated reference authentication</Heading>
        <p className="context-note">
          Not recorded by this historical assessment policy.
        </p>
      </div>
    );
  }
  return (
    <div className="assessment-subsection">
      <Heading>Curated reference authentication</Heading>
      <p>
        <strong>Status:</strong> {authStatusLabels[auth.status] ?? auth.status}
      </p>
      <p className="context-note">
        Curated reference authentication verifies only exact whole-file bytes of
        an already curated EPUB copy. Changed or repackaged candidates remain
        different bytes or unconfirmed.
      </p>
      <p className="context-note">
        Historical observation at {auth.checked_at ?? "an unrecorded time"}.
      </p>
      {auth.reason_codes.length > 0 && (
        <p className="context-note">
          Recorded reasons: {auth.reason_codes.join(", ")}
        </p>
      )}
      <dl className="assessment-grid">
        <div>
          <dt>Reference ID</dt>
          <dd>{auth.reference_id ?? "None selected"}</dd>
        </div>
        <div>
          <dt>Authority ID</dt>
          <dd>{auth.authority_id ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Work identity claim</dt>
          <dd>
            {auth.claims.includes("work_identity")
              ? "Supported"
              : "Unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Edition identity claim</dt>
          <dd>
            {auth.claims.includes("edition_identity")
              ? "Supported"
              : "Unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Complete collection claim</dt>
          <dd>
            {auth.claims.includes("complete_collection")
              ? "Supported"
              : "Unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Language / revision claims</dt>
          <dd>
            {auth.claims.includes("language") ? "Supported" : "Unconfirmed"} /{" "}
            {auth.claims.includes("revision") ? "Supported" : "Unconfirmed"}
          </dd>
        </div>
        {auth.reference_publication && (
          <div>
            <dt>Reference publication provenance</dt>
            <dd>
              Work {auth.reference_publication.work_id ?? "unknown"}
              {auth.reference_publication.edition_id
                ? ` · Edition ${auth.reference_publication.edition_id}`
                : ""}
              {auth.reference_publication.catalogue_version
                ? ` · Curated at snapshot ${auth.reference_publication.catalogue_version}`
                : ""}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function AssessmentReportView({
  report,
  level = 5,
}: {
  report: BookAssessmentReport;
  level?: 4 | 5;
}) {
  const Heading = level === 4 ? "h4" : "h5";
  const Subheading = level === 4 ? "h5" : "h6";

  return (
    <div className="assessment-outcome-panel">
      <Heading>Recorded candidate assessment</Heading>
      <p>{distinctScope(report.scope, "Correction admission remains held.")}</p>
      <dl className="assessment-grid">
        <div>
          <dt>File work identity</dt>
          <dd>
            <strong>{report.file_work_identity.status}</strong> (work{" "}
            {report.file_work_identity.work_id}) · basis:{" "}
            {report.file_work_identity.basis || "none"}
          </dd>
        </div>
        <div>
          <dt>Edition identity</dt>
          <dd>
            <strong>{report.edition_identity.status}</strong>
            {report.edition_identity.edition_id
              ? ` (${report.edition_identity.edition_id})`
              : " · no confirmed edition"}{" "}
            · language/content equivalence:{" "}
            {report.edition_identity.language_and_content_equivalence}
          </dd>
        </div>
        <div>
          <dt>Source provenance</dt>
          <dd>
            {report.source_provenance?.kind === "native_library" ||
            report.library_origin
              ? `Native library (${report.library_origin?.book_id ?? "book"})`
              : report.source_provenance?.kind === "incoming_upload"
                ? "Incoming upload"
                : "Not recorded by this historical policy"}
          </dd>
        </div>
        <div>
          <dt>Current library bytes at assessment</dt>
          <dd>{report.current_library_bytes.status}</dd>
        </div>
      </dl>

      <ReferenceAuthenticationSection
        auth={report.reference_authentication}
        level={level}
      />
      <details>
        <summary>Recorded title and credit evidence</summary>
        <p>
          {report.source_attribution?.status ??
            "Not recorded by this historical assessment policy"}
        </p>
      </details>

      <div className="assessment-subsection">
        <Heading>Duplicate and overlap evidence</Heading>
        <p className="context-note">
          Other-format bytes and shared document text are review leads. Semantic
          duplicate clearance remains unconfirmed.
        </p>
        <dl className="assessment-grid">
          <div>
            <dt>Exact byte matches in library</dt>
            <dd>
              <strong>{report.duplicates.exact_bytes.status}</strong> (
              {report.duplicates.exact_bytes.count.toLocaleString()})
              {report.duplicates.exact_bytes.books.length > 0 && (
                <ul>
                  {report.duplicates.exact_bytes.books.map((b, i) => (
                    <li key={i}>
                      {b.book_id} ({b.format})
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
          <div>
            <dt>Possible same-work candidates</dt>
            <dd>
              <strong>{report.duplicates.same_work.status}</strong> (
              {report.duplicates.same_work.count.toLocaleString()})
              {report.duplicates.same_work.candidates.length > 0 && (
                <ul>
                  {report.duplicates.same_work.candidates.map((c, i) => (
                    <li key={i}>
                      {c.book_id} · {c.basis.join(", ")}
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
          <div>
            <dt>Other recorded formats (non-EPUB)</dt>
            <dd>
              {report.duplicates.other_formats ? (
                <>
                  {report.duplicates.other_formats.count.toLocaleString()} (
                  {report.duplicates.other_formats.status};{" "}
                  {report.duplicates.other_formats.byte_comparison})
                  {report.duplicates.other_formats.files.length > 0 && (
                    <ul>
                      {report.duplicates.other_formats.files.map((f, i) => (
                        <li key={i}>
                          {f.book_id} ({f.format})
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                "Not recorded by this historical assessment policy"
              )}
            </dd>
          </div>
          <div>
            <dt>Content duplicate clearance</dt>
            <dd>
              <strong>
                {report.duplicates.content?.clearance ?? "Unconfirmed"}
              </strong>{" "}
              ·{" "}
              {report.duplicates.content?.possible_count.toLocaleString() ??
                "Unknown"}{" "}
              possible
            </dd>
          </div>
        </dl>

        {!!report.duplicates.content?.comparisons.length && (
          <div>
            <Subheading>Explicit preserved inspection comparisons</Subheading>
            <ul className="assessment-choice-list">
              {report.duplicates.content.comparisons.map((comp, idx) => (
                <li key={idx}>
                  <p>
                    <strong>Inspection {comp.inspection.job_id}</strong>{" "}
                    {comp.book_id ? `(library book ${comp.book_id})` : ""} ·
                    relationship: {comp.relationship} · whole-text relation:{" "}
                    {comp.text_relation}
                  </p>
                  <SpineOverlapSection
                    title="Spine resource overlap"
                    overlap={comp.resource_overlap}
                  />
                  <SpineOverlapSection
                    title="Spine document body text overlap"
                    overlap={comp.document_text_overlap}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function CandidateAssessment({
  source,
  pin,
  work,
  session,
  jobs = [],
  assessmentId = "",
  selectAssessment,
  onJob,
  cancel,
  cancelling,
  announceTerminal,
}: {
  source: Job;
  pin: CatalogueSnapshotPin;
  work: { id: string; title: string };
  session?: Session;
  jobs?: Job[];
  assessmentId?: string;
  selectAssessment?: (id: string) => void;
  onJob?: (job: Job) => void;
  cancel?: (job: Job) => void;
  cancelling?: string;
  announceTerminal?: (jobs: Job[]) => void;
}) {
  const workspace = useBookWorkspace();
  const id = useId();
  const client = useQueryClient();
  const csrf = session?.csrf;

  // 1. Saved reconciliations & reconciliation jobs
  const [reconciliationPage, setReconciliationPage] = useState(1);
  const [reconcileJobPage, setReconcileJobPage] = useState(1);
  const [selectedReconciliation, setSelectedReconciliation] = useState("");
  const chosenReconciliation = useRef<SavedReconciliationSummary | null>(null);
  const [moreReconciliations, setMoreReconciliations] = useState(false);
  const [reconcileAttempt, setReconcileAttempt] = useState<{
    intent: ReconciliationIntent;
    outcome: "pending" | "unconfirmed" | "refused";
    reason: string;
  } | null>(() => {
    const saved = readReconciliationIntent(pin.version, pin.sha256);
    return saved
      ? {
          intent: saved,
          outcome: "unconfirmed",
          reason:
            "This page was reloaded before the reconciliation request was confirmed.",
        }
      : null;
  });
  const [reconcileWorking, setReconcileWorking] = useState<
    "idle" | "starting" | "recovering"
  >("idle");
  const [reconciledJob, setReconciledJob] = useState<Job | null>(null);
  const reconcileOp = useRef<AbortController | null>(null);
  const reconcileSelection = useRef<AbortController | null>(null);
  const [reconciliationNotice, setReconciliationNotice] = useState("");

  const savedReconciliationsQuery = useQuery({
    queryKey: [
      "saved-reconciliations",
      pin.version,
      pin.sha256,
      reconciliationPage,
    ],
    queryFn: ({ signal }) =>
      fetchSavedReconciliations(pin, reconciliationPage, signal),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const reconciliationJobsQuery = useQuery({
    queryKey: ["reconciliation-jobs", reconcileJobPage],
    queryFn: ({ signal }) =>
      fetchReconciliationJobHistory(reconcileJobPage, signal),
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.jobs.some(active) ? 1500 : false,
  });

  const reconciliationDetail = useQuery<Job>({
    queryKey: ["selected-reconciliation-job", reconciledJob?.id],
    enabled: !!reconciledJob,
    queryFn: async ({ signal }) => {
      const job = await api<Job>(
        `jobs/${encodeURIComponent(reconciledJob!.id)}`,
        { signal },
      );
      if (
        job.id !== reconciledJob!.id ||
        job.kind !== "library_reconcile" ||
        (job.catalogue_version ?? job.source_version) !== pin.version ||
        (job.catalogue_sha256 ?? job.source_sha256) !== pin.sha256
      ) {
        throw new Error(
          "The reconciliation does not match the selected catalogue.",
        );
      }
      return job;
    },
    retry: false,
    refetchInterval: (query) =>
      active(query.state.data ?? reconciledJob!) ? 1500 : false,
    structuralSharing: (old, incoming) =>
      newer(old as Job | undefined, incoming as Job)!,
  });
  const currentReconciliationJob = newer(
    jobs.find((job) => job.id === reconciledJob?.id),
    newer(reconciliationDetail.data, reconciledJob ?? undefined),
  );
  useEffect(() => {
    if (!currentReconciliationJob) return;
    onJob?.(currentReconciliationJob);
    announceTerminal?.([currentReconciliationJob]);
    if (!active(currentReconciliationJob)) {
      void client.invalidateQueries({ queryKey: ["saved-reconciliations"] });
      void client.invalidateQueries({ queryKey: ["reconciliation-jobs"] });
    }
  }, [currentReconciliationJob?.id, currentReconciliationJob?.revision]);

  async function startReconciliation(retry = false) {
    if (workspace?.ready === false) return;
    if (!csrf || reconcileWorking !== "idle") return;
    reconcileOp.current?.abort();
    const controller = new AbortController();
    reconcileOp.current = controller;
    setReconcileWorking("starting");
    let intent: ReconciliationIntent | null =
      retry && reconcileAttempt ? reconcileAttempt.intent : null;
    try {
      if (!intent) {
        const inv = await fetchDirectLibraryInventory(controller.signal);
        if (controller.signal.aborted) return;
        intent = {
          key: crypto.randomUUID(),
          version: pin.version,
          sha256: pin.sha256,
          inventory_token: inv.token,
          library_uuid: inv.library_uuid ?? null,
          previous: selectedReconciliation || null,
        };
      }
      saveReconciliationIntent(intent);
      setReconcileAttempt({ intent, outcome: "pending", reason: "" });
      const job = await requestReconciliationJob({
        csrf,
        intent,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      clearReconciliationIntent(pin.version, pin.sha256, job.request_key);
      setReconcileAttempt(null);
      setReconciledJob(job);
      onJob?.(job);
      void client.invalidateQueries({ queryKey: ["saved-reconciliations"] });
      void client.invalidateQueries({ queryKey: ["reconciliation-jobs"] });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (!intent) {
        setReconcileAttempt({
          intent: {
            key: crypto.randomUUID(),
            version: pin.version,
            sha256: pin.sha256,
            inventory_token: "0".repeat(64),
            library_uuid: null,
            previous: null,
          },
          outcome: "refused",
          reason:
            error instanceof Error
              ? error.message
              : "Direct library inventory could not be read.",
        });
      } else if (
        error instanceof ApiError &&
        error.status < 500 &&
        error.status !== 408
      ) {
        clearReconciliationIntent(pin.version, pin.sha256, intent.key);
        setReconcileAttempt({
          intent,
          outcome: "refused",
          reason: error.message,
        });
      } else {
        setReconcileAttempt({
          intent,
          outcome: "unconfirmed",
          reason:
            "The service did not confirm whether library reconciliation was queued.",
        });
        setReconcileWorking("recovering");
        await lookupReconciliation(intent, controller);
      }
    } finally {
      if (reconcileOp.current === controller) {
        reconcileOp.current = null;
        setReconcileWorking("idle");
      }
    }
  }

  async function lookupReconciliation(
    intent: ReconciliationIntent,
    controller: AbortController,
  ) {
    try {
      const job = await recoverReconciliationJob(intent.key, controller.signal);
      if (controller.signal.aborted) return;
      clearReconciliationIntent(pin.version, pin.sha256, job.request_key);
      setReconcileAttempt(null);
      setReconciledJob(job);
      onJob?.(job);
      void client.invalidateQueries({ queryKey: ["saved-reconciliations"] });
      void client.invalidateQueries({ queryKey: ["reconciliation-jobs"] });
    } catch (error) {
      if (controller.signal.aborted) return;
      setReconcileAttempt({
        intent,
        outcome: "unconfirmed",
        reason:
          error instanceof ApiError && error.status === 404
            ? "The reconciliation request is not recorded yet."
            : error instanceof Error
              ? error.message
              : "The reconciliation request status could not be confirmed.",
      });
    }
  }

  // 2. Comparison inspections selection (0 to 8 pin objects)
  const [extraComparisons, setExtraComparisons] = useState<Job[]>([]);
  const [comparisonId, setComparisonId] = useState("");
  const [comparisonLookup, setComparisonLookup] = useState("");
  const comparisonOp = useRef<AbortController | null>(null);
  async function addComparison() {
    if (comparisonOp.current) return;
    if (!ANY_UUID_PATTERN.test(comparisonId)) {
      setComparisonLookup("Enter a saved inspection UUID from Reviews.");
      return;
    }
    const controller = new AbortController();
    comparisonOp.current = controller;
    setComparisonLookup("Loading comparison inspection…");
    try {
      const candidate = await api<Job>(
        `jobs/${encodeURIComponent(comparisonId)}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      if (
        candidate.id !== comparisonId ||
        candidate.kind !== "epub" ||
        candidate.state !== "succeeded" ||
        candidate.id === source.id ||
        !DIGEST_PATTERN.test(candidate.source_sha256 ?? "") ||
        !DIGEST_PATTERN.test(candidate.result?.report_sha256 ?? "")
      )
        throw new Error("Choose another completed preserved EPUB inspection.");
      setExtraComparisons((current) => [
        ...current.filter((item) => item.id !== candidate.id),
        candidate,
      ]);
      setComparisonLookup(
        "Comparison inspection loaded. Select it below to include it.",
      );
      setComparisonId("");
    } catch (error) {
      if (!controller.signal.aborted)
        setComparisonLookup(
          error instanceof Error
            ? error.message
            : "Comparison inspection could not be loaded.",
        );
    } finally {
      if (comparisonOp.current === controller) comparisonOp.current = null;
    }
  }
  const eligibleComparisons = [
    ...new Map(
      [...jobs, ...extraComparisons].map((job) => [job.id, job]),
    ).values(),
  ].filter(
    (j) =>
      j.kind === "epub" &&
      j.state === "succeeded" &&
      j.id !== source.id &&
      typeof j.source_sha256 === "string" &&
      typeof j.result.report_sha256 === "string",
  );
  const [selectedComparisons, setSelectedComparisons] = useState<
    ComparisonInspectionPin[]
  >([]);
  const [moreComparisons, setMoreComparisons] = useState(false);
  const [lastComparison, setLastComparison] = useState("");
  useEffect(() => setLastComparison(""), [source.id]);

  // 3. Curated reference discovery and selection
  const referencesQuery = useQuery({
    queryKey: ["content-trust-references", pin.version, pin.sha256, work.id],
    queryFn: ({ signal }) => fetchContentReferences(pin, work.id, signal),
    retry: false,
  });
  const [selectedReference, setSelectedReference] =
    useState<ReferenceSelectionPin | null>(null);
  const currentReference =
    selectedReference &&
    !referencesQuery.isError &&
    referencesQuery.data?.status === "available" &&
    referencesQuery.data.registry_sha256 ===
      selectedReference.registry_sha256 &&
    referencesQuery.data.references.some(
      (ref) =>
        ref.reference_id === selectedReference.reference_id &&
        ref.manifest_sha256 === selectedReference.manifest_sha256,
    )
      ? selectedReference
      : null;
  useEffect(() => {
    if (selectedReference && !currentReference) setSelectedReference(null);
  }, [currentReference, selectedReference]);

  // 4. Candidate assessment launch / recovery / history
  const [checkPage, setCheckPage] = useState(1);
  const [moreAssessments, setMoreAssessments] = useState(false);
  const [discoveredCheckId, setDiscoveredCheckId] = useState("");
  const [checkAttempt, setCheckAttempt] = useState<{
    intent: AssessmentIntent;
    outcome: "pending" | "unconfirmed" | "refused";
    reason: string;
  } | null>(() => {
    const saved = readAssessmentIntent(source);
    return saved &&
      saved.version === pin.version &&
      saved.sha256 === pin.sha256 &&
      saved.catalogue_work_id === work.id
      ? {
          intent: saved,
          outcome: "unconfirmed",
          reason:
            "This page was closed or reloaded before the candidate assessment was confirmed.",
        }
      : null;
  });
  const [checkWorking, setCheckWorking] = useState<
    "idle" | "starting" | "recovering"
  >("idle");
  const checkOp = useRef<AbortController | null>(null);
  const recoveredInitialCheck = useRef(false);

  const selectedCheckId = assessmentId || discoveredCheckId;

  const checkHistoryQuery = useQuery({
    queryKey: ["candidate-assessment-history", source.id, checkPage],
    queryFn: ({ signal }) =>
      fetchCandidateAssessmentHistory(source, checkPage, signal),
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.jobs.some(active) ||
      checkAttempt?.outcome === "unconfirmed"
        ? 1500
        : false,
  });

  const checkDetailQuery = useQuery({
    queryKey: ["candidate-assessment-job", source.id, selectedCheckId],
    enabled: !!selectedCheckId,
    queryFn: async ({ signal }) => {
      const job = await api<Job>(
        `jobs/${encodeURIComponent(selectedCheckId)}`,
        { signal },
      );
      if (job.id !== selectedCheckId || !assessmentJobBinds(source, job)) {
        throw new Error(
          "The selected candidate assessment does not match this preserved source.",
        );
      }
      return job;
    },
    retry: false,
    refetchInterval: (query) =>
      query.state.data && active(query.state.data) ? 1500 : false,
    structuralSharing: (old, incoming) =>
      newer(old as Job | undefined, incoming as Job)!,
  });

  const activeCheckJob = newer(
    jobs.find((j) => j.id === selectedCheckId && assessmentJobBinds(source, j)),
    checkDetailQuery.data?.id === selectedCheckId
      ? checkDetailQuery.data
      : undefined,
  );

  // If the user changes any bound selection (reconciliation, comparison pins, or reference),
  // any stored intent for a different selection must not be reused.
  function makeCurrentAssessmentIntent(): AssessmentIntent {
    const existing = checkAttempt?.intent;
    if (
      existing &&
      existing.version === pin.version &&
      existing.sha256 === pin.sha256 &&
      existing.catalogue_work_id === work.id &&
      existing.reconciliation === selectedReconciliation &&
      sameComparisonPins(
        existing.comparison_inspections,
        selectedComparisons,
      ) &&
      sameReferencePin(existing.reference, currentReference)
    ) {
      return existing;
    }
    return {
      key: crypto.randomUUID(),
      source_job_id: source.id,
      source_sha256: source.source_sha256!,
      report_sha256: source.result.report_sha256!,
      version: pin.version,
      sha256: pin.sha256,
      catalogue_work_id: work.id,
      reconciliation: selectedReconciliation,
      comparison_inspections: selectedComparisons,
      reference: currentReference,
    };
  }

  function confirmCheckJob(job: Job, signal: AbortSignal) {
    if (signal.aborted) return;
    clearAssessmentIntent(source.id, job.request_key);
    setCheckAttempt(null);
    client.setQueryData<Job>(
      ["candidate-assessment-job", source.id, job.id],
      (prev) => newer(prev, job)!,
    );
    onJob?.(job);
    setDiscoveredCheckId(job.id);
    selectAssessment?.(job.id);
    void client.invalidateQueries({
      queryKey: ["candidate-assessment-history", source.id],
    });
  }

  async function lookupCheck(
    intent: AssessmentIntent,
    controller: AbortController,
  ) {
    try {
      const job = await recoverCandidateAssessment(
        source,
        intent.key,
        controller.signal,
      );
      confirmCheckJob(job, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      const refused = error instanceof ApiError && error.status === 409;
      if (refused) clearAssessmentIntent(source.id, intent.key);
      setCheckAttempt({
        intent,
        outcome: refused ? "refused" : "unconfirmed",
        reason:
          error instanceof ApiError && error.status === 404
            ? "The candidate assessment request is not recorded yet."
            : error instanceof Error
              ? error.message
              : "The candidate assessment request status could not be confirmed.",
      });
    }
  }

  async function startAssessment(retry = false) {
    if (workspace?.ready === false) return;
    if (!csrf || (!retry && !selectedReconciliation) || checkWorking !== "idle")
      return;
    checkOp.current?.abort();
    const controller = new AbortController();
    checkOp.current = controller;
    setCheckWorking("starting");
    const intent =
      retry && checkAttempt
        ? checkAttempt.intent
        : makeCurrentAssessmentIntent();
    saveAssessmentIntent(intent);
    setCheckAttempt({ intent, outcome: "pending", reason: "" });
    try {
      const job = await requestCandidateAssessment({
        source,
        csrf,
        intent,
        signal: controller.signal,
      });
      confirmCheckJob(job, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (
        error instanceof ApiError &&
        error.status < 500 &&
        error.status !== 408
      ) {
        clearAssessmentIntent(source.id, intent.key);
        setCheckAttempt({
          intent,
          outcome: "refused",
          reason: error.message,
        });
      } else {
        setCheckAttempt({
          intent,
          outcome: "unconfirmed",
          reason:
            "The service did not confirm whether this candidate assessment was queued.",
        });
        setCheckWorking("recovering");
        await lookupCheck(intent, controller);
      }
    } finally {
      if (checkOp.current === controller) {
        checkOp.current = null;
        setCheckWorking("idle");
      }
    }
  }

  useEffect(() => {
    if (
      recoveredInitialCheck.current ||
      !checkAttempt ||
      checkAttempt.outcome !== "unconfirmed" ||
      assessmentId
    )
      return;
    recoveredInitialCheck.current = true;
    const controller = new AbortController();
    checkOp.current = controller;
    setCheckWorking("recovering");
    void lookupCheck(checkAttempt.intent, controller).finally(() => {
      if (checkOp.current === controller) {
        checkOp.current = null;
        setCheckWorking("idle");
      }
    });
  }, [assessmentId]);

  useEffect(() => {
    if (activeCheckJob) {
      onJob?.(activeCheckJob);
      announceTerminal?.([activeCheckJob]);
    }
  }, [activeCheckJob?.id, activeCheckJob?.revision]);

  useEffect(
    () => () => {
      reconcileOp.current?.abort();
      reconcileSelection.current?.abort();
      checkOp.current?.abort();
      comparisonOp.current?.abort();
    },
    [],
  );

  function toggleComparisonPin(candidate: Job) {
    const pinObj: ComparisonInspectionPin = {
      job_id: candidate.id,
      source_sha256: candidate.source_sha256!,
      report_sha256: candidate.result.report_sha256!,
    };
    setSelectedComparisons((current) => {
      const exists = current.some((item) => item.job_id === candidate.id);
      if (exists) {
        return current.filter((item) => item.job_id !== candidate.id);
      }
      if (current.length >= 8) return current;
      return [...current, pinObj];
    });
  }

  const boundReport = activeCheckJob
    ? extractAssessmentReport(source, activeCheckJob)
    : null;
  const reconciliationRows = [
    ...(savedReconciliationsQuery.data?.reports ?? []),
  ];
  const retainedReconciliation = chosenReconciliation.current;
  if (
    retainedReconciliation?.request_key === selectedReconciliation &&
    retainedReconciliation.catalogue.version === pin.version &&
    retainedReconciliation.catalogue.sha256 === pin.sha256 &&
    !reconciliationRows.some(
      (row) => row.request_key === selectedReconciliation,
    )
  )
    reconciliationRows.push(retainedReconciliation);
  const extraReconciliations = reconciliationRows
    .slice(3)
    .filter((row) => row.request_key !== selectedReconciliation).length;
  type HistoryChoice = Pick<
    Job,
    | "id"
    | "title"
    | "state"
    | "catalogue_version"
    | "catalogue_sha256"
    | "catalogue_work_id"
  >;
  const assessmentRows: HistoryChoice[] = [
    ...(checkHistoryQuery.data?.jobs ?? []),
  ];
  if (
    activeCheckJob &&
    !assessmentRows.some((row) => row.id === activeCheckJob.id)
  )
    assessmentRows.push(activeCheckJob);
  const extraAssessments = assessmentRows
    .slice(3)
    .filter((row) => row.id !== selectedCheckId).length;
  const additionalComparisonCount = eligibleComparisons
    .slice(3)
    .filter(
      (row) =>
        row.id !== lastComparison &&
        !selectedComparisons.some((selected) => selected.job_id === row.id),
    ).length;

  return (
    <section className="candidate-assessment" aria-labelledby={`${id}-heading`}>
      <h4 id={`${id}-heading`}>
        Candidate assessment and library reconciliation
      </h4>
      <p className="comparison-intro">
        Assess this preserved EPUB against the selected catalogue work (
        <strong>{work.title}</strong>, snapshot {pin.version}) and an explicit
        saved library reconciliation.
      </p>
      {/* Step 1: Saved library reconciliation selection & runner */}
      <div className="assessment-subsection">
        <h5>1. Saved library reconciliation</h5>
        {savedReconciliationsQuery.isPending ? (
          <p role="status">Loading saved reconciliations…</p>
        ) : savedReconciliationsQuery.isError ? (
          <div className="error" role="alert">
            <p>{savedReconciliationsQuery.error.message}</p>
            <button
              type="button"
              onClick={() => void savedReconciliationsQuery.refetch()}
            >
              Retry saved reconciliations
            </button>
          </div>
        ) : reconciliationRows.length ? (
          <ul
            id={`${id}-saved-reconciliations`}
            className="assessment-choice-list"
            aria-label="Saved library reconciliations"
          >
            {reconciliationRows.map((rep, index) => (
              <li
                key={rep.request_key}
                hidden={
                  !moreReconciliations &&
                  index >= 3 &&
                  rep.request_key !== selectedReconciliation
                }
              >
                <label className="assessment-choice-label">
                  <input
                    type="radio"
                    id={`${id}-reconciliation-${rep.request_key}`}
                    name={`${id}-reconciliation`}
                    checked={selectedReconciliation === rep.request_key}
                    onChange={() => {
                      chosenReconciliation.current = rep;
                      setSelectedReconciliation(rep.request_key);
                    }}
                  />
                  <span className="assessment-choice-body">
                    <span className="assessment-code">{rep.request_key}</span>
                    <span className="assessment-choice-meta">
                      Created {new Date(rep.created_at).toLocaleString()} ·{" "}
                      {rep.total.toLocaleString()} library{" "}
                      {rep.total === 1 ? "book" : "books"} · inventory{" "}
                      {rep.inventory.token.slice(0, 12)}…
                    </span>
                    {!savedReconciliationsQuery.data?.reports.some(
                      (row) => row.request_key === rep.request_key,
                    ) && (
                      <span className="assessment-choice-meta">
                        Selected from another page
                      </span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <p className="context-note">
            No saved reconciliation matches catalogue snapshot {pin.version}.
            Run a library reconciliation below before launching candidate
            assessment.
          </p>
        )}

        {!savedReconciliationsQuery.isPending &&
          !savedReconciliationsQuery.isError &&
          extraReconciliations > 0 && (
            <button
              type="button"
              className="text-button assessment-history-toggle"
              aria-expanded={moreReconciliations}
              aria-controls={`${id}-saved-reconciliations`}
              onClick={() => setMoreReconciliations((value) => !value)}
            >
              {moreReconciliations
                ? "Fewer saved reconciliations"
                : "More saved reconciliations"}{" "}
              · {extraReconciliations} additional on this page
            </button>
          )}

        <AssessmentPages
          data={savedReconciliationsQuery.data}
          label="reconciliation"
          change={setReconciliationPage}
        />

        {csrf && (
          <div className="actions">
            <button
              type="button"
              className="secondary"
              aria-disabled={reconcileWorking !== "idle"}
              onClick={() => void startReconciliation(false)}
            >
              {reconcileWorking === "starting"
                ? "Running library reconciliation…"
                : "Run library reconciliation"}
            </button>
          </div>
        )}

        {reconcileAttempt?.outcome === "unconfirmed" && (
          <div className="error" role="alert">
            <p>{reconcileAttempt.reason}</p>
            <div className="actions">
              <button
                type="button"
                disabled={reconcileWorking !== "idle"}
                onClick={() => {
                  if (reconcileOp.current) return;
                  const controller = new AbortController();
                  reconcileOp.current = controller;
                  setReconcileWorking("recovering");
                  void lookupReconciliation(
                    reconcileAttempt.intent,
                    controller,
                  ).finally(() => {
                    if (reconcileOp.current === controller) {
                      reconcileOp.current = null;
                      setReconcileWorking("idle");
                    }
                  });
                }}
              >
                Check reconciliation request
              </button>
              {csrf && (
                <button
                  type="button"
                  onClick={() => void startReconciliation(true)}
                >
                  Retry reconciliation request
                </button>
              )}
            </div>
          </div>
        )}
        {reconcileAttempt?.outcome === "refused" && (
          <p className="error" role="alert">
            {reconcileAttempt.reason}
          </p>
        )}
        {currentReconciliationJob && (
          <div>
            <JobProgress job={currentReconciliationJob} />
            {currentReconciliationJob.state === "succeeded" && (
              <p>
                Select the saved reconciliation above to use it for an
                assessment.
              </p>
            )}
            {active(currentReconciliationJob) && cancel && (
              <button
                type="button"
                className="cancel"
                disabled={cancelling === currentReconciliationJob.id}
                onClick={() => cancel(currentReconciliationJob)}
              >
                {cancelling === currentReconciliationJob.id
                  ? "Cancelling…"
                  : "Cancel reconciliation"}
              </button>
            )}
          </div>
        )}
        {reconciliationDetail.isError && (
          <p role="alert" className="error">
            {reconciliationDetail.error.message}
          </p>
        )}
        {reconciliationJobsQuery.isError && (
          <p role="alert" className="error">
            {reconciliationJobsQuery.error.message}
          </p>
        )}
        {!!reconciliationJobsQuery.data?.jobs.length && (
          <details>
            <summary>Reconciliation request history</summary>
            <ul className="assessment-history-list">
              {reconciliationJobsQuery.data.jobs.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={async () => {
                      reconcileSelection.current?.abort();
                      const controller = new AbortController();
                      reconcileSelection.current = controller;
                      setReconciliationNotice("");
                      try {
                        const full = await api<Job>(
                          `jobs/${encodeURIComponent(item.id)}`,
                          { signal: controller.signal },
                        );
                        if (controller.signal.aborted) return;
                        if (
                          full.id !== item.id ||
                          full.kind !== "library_reconcile" ||
                          (full.catalogue_version ?? full.source_version) !==
                            pin.version ||
                          (full.catalogue_sha256 ?? full.source_sha256) !==
                            pin.sha256
                        )
                          throw new Error(
                            "This reconciliation belongs to another catalogue snapshot.",
                          );
                        setReconciledJob(full);
                      } catch (error) {
                        if (!controller.signal.aborted)
                          setReconciliationNotice(
                            error instanceof Error
                              ? error.message
                              : "Saved request could not be opened.",
                          );
                      }
                    }}
                  >
                    {item.title} ({item.id})
                  </button>
                  <span>{item.state}</span>
                </li>
              ))}
            </ul>
            <AssessmentPages
              data={reconciliationJobsQuery.data}
              label="reconciliation request"
              change={setReconcileJobPage}
            />
          </details>
        )}
        {reconciliationNotice && (
          <p role="alert" className="error">
            {reconciliationNotice}
          </p>
        )}
      </div>

      {/* Step 2: Explicit comparison inspections (0 to 8 pin objects) */}
      <div className="assessment-subsection">
        <h5>
          2. Comparison inspections ({selectedComparisons.length} of 8 selected)
        </h5>
        <p className="context-note">
          Select up to 8 completed EPUB inspections to compare reading-order
          spine resource digests and normalized document body text.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void addComparison();
          }}
        >
          <label htmlFor={`${id}-comparison`}>
            Preserved comparison inspection ID
          </label>
          <input
            id={`${id}-comparison`}
            value={comparisonId}
            onChange={(event) => setComparisonId(event.target.value)}
            maxLength={36}
          />
          <button type="submit">Add comparison inspection</button>
          {comparisonLookup && <p role="status">{comparisonLookup}</p>}
        </form>
        {eligibleComparisons.length ? (
          <ul
            id={`${id}-comparison-inspections`}
            className="assessment-choice-list"
            aria-label="Comparison EPUB inspections"
          >
            {eligibleComparisons.map((comp, index) => {
              const checked = selectedComparisons.some(
                (item) => item.job_id === comp.id,
              );
              const disabled = !checked && selectedComparisons.length >= 8;
              return (
                <li
                  key={comp.id}
                  hidden={
                    !moreComparisons &&
                    index >= 3 &&
                    !checked &&
                    comp.id !== lastComparison
                  }
                >
                  <label className="assessment-choice-label">
                    <input
                      type="checkbox"
                      id={`${id}-comparison-${comp.id}`}
                      checked={checked}
                      disabled={disabled}
                      onChange={() => {
                        if (index >= 3) setLastComparison(comp.id);
                        toggleComparisonPin(comp);
                      }}
                    />
                    <span className="assessment-choice-body">
                      <strong>{comp.title}</strong> ({comp.id})
                      <span className="assessment-choice-meta">
                        Source {comp.source_sha256?.slice(0, 12)}… · Report{" "}
                        {comp.result.report_sha256?.slice(0, 12)}…
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="context-note">
            No other completed EPUB inspections are currently loaded for
            comparison.
          </p>
        )}
        {additionalComparisonCount > 0 && (
          <button
            type="button"
            className="text-button assessment-history-toggle"
            aria-expanded={moreComparisons}
            aria-controls={`${id}-comparison-inspections`}
            onClick={() => {
              setLastComparison("");
              setMoreComparisons((value) => !value);
            }}
          >
            {moreComparisons
              ? "Fewer comparison inspections"
              : "More comparison inspections"}{" "}
            · {additionalComparisonCount} additional loaded
          </button>
        )}
      </div>

      {/* Step 3: Optional configured curated-reference selection */}
      <div className="assessment-subsection">
        <h5>3. Curated reference authentication (optional)</h5>
        <p className="context-note">
          Locally curated references authenticate only exact whole-file bytes of
          an already curated copy. No external authority or automatic trust root
          is used.
        </p>
        {referencesQuery.isPending ? (
          <p role="status">Checking curated references…</p>
        ) : referencesQuery.isError ? (
          <div className="error" role="alert">
            <p>{referencesQuery.error.message}</p>
            <button
              type="button"
              onClick={() => void referencesQuery.refetch()}
            >
              Retry reference discovery
            </button>
          </div>
        ) : referencesQuery.data?.status === "not_configured" ? (
          <p className="context-note">
            No local curated reference registry is configured on this
            connection. Candidate assessment remains usable with authentication
            status not requested.
          </p>
        ) : referencesQuery.data?.status === "unavailable" ? (
          <p className="context-note">
            Curated reference registry is currently unavailable (
            {referencesQuery.data.reason_codes.join(", ") || "unreadable"}).
          </p>
        ) : referencesQuery.data?.references.length ? (
          <ul
            className="assessment-choice-list"
            aria-label="Discovered curated references"
          >
            {referencesQuery.data.references.map((ref) => {
              const checked = sameReferencePin(currentReference, {
                reference_id: ref.reference_id,
                registry_sha256: referencesQuery.data!.registry_sha256!,
                manifest_sha256: ref.manifest_sha256,
              });
              return (
                <li key={ref.reference_id}>
                  <label className="assessment-choice-label">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        if (checked) {
                          setSelectedReference(null);
                        } else if (referencesQuery.data?.registry_sha256) {
                          setSelectedReference({
                            reference_id: ref.reference_id,
                            registry_sha256:
                              referencesQuery.data.registry_sha256,
                            manifest_sha256: ref.manifest_sha256,
                          });
                        }
                      }}
                    />
                    <span className="assessment-choice-body">
                      <strong>{ref.reference_id}</strong> · Authority{" "}
                      {ref.authority_id}
                      <span className="assessment-choice-meta">
                        Edition {ref.publication.edition_id ?? "unassigned"} ·
                        Scope {ref.publication.scope} · Curated scope (not yet
                        verified): {ref.claims.join(", ")} · Artifact SHA-256{" "}
                        {ref.artifact.sha256.slice(0, 12)}…
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="context-note">
            No active curated reference is recorded for work {work.id}.
          </p>
        )}
      </div>

      {/* Step 4: Launch / recover / view candidate assessment */}
      <div className="assessment-subsection">
        <h5>4. Candidate assessment</h5>
        {csrf && (
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={!selectedReconciliation || checkWorking !== "idle"}
              onClick={() => void startAssessment(false)}
            >
              {checkWorking === "starting"
                ? "Starting candidate assessment…"
                : "Run candidate assessment"}
            </button>
          </div>
        )}

        {checkAttempt?.outcome === "unconfirmed" && (
          <div className="error" role="alert">
            <p>{checkAttempt.reason}</p>
            <div className="actions">
              <button
                type="button"
                disabled={checkWorking !== "idle"}
                onClick={() => {
                  if (checkOp.current) return;
                  const controller = new AbortController();
                  checkOp.current = controller;
                  setCheckWorking("recovering");
                  void lookupCheck(checkAttempt.intent, controller).finally(
                    () => {
                      if (checkOp.current === controller) {
                        checkOp.current = null;
                        setCheckWorking("idle");
                      }
                    },
                  );
                }}
              >
                Check candidate assessment request
              </button>
              {csrf && (
                <button
                  type="button"
                  disabled={checkWorking !== "idle"}
                  onClick={() => void startAssessment(true)}
                >
                  Retry this candidate assessment request
                </button>
              )}
            </div>
          </div>
        )}

        {checkAttempt?.outcome === "refused" && (
          <div className="error" role="alert">
            <p>{checkAttempt.reason}</p>
          </div>
        )}
        {checkDetailQuery.isPending && selectedCheckId && (
          <p role="status">Loading selected assessment…</p>
        )}
        {checkDetailQuery.isError && (
          <p className="error" role="alert">
            {checkDetailQuery.error.message}
          </p>
        )}
        {checkHistoryQuery.isError && (
          <p className="error" role="alert">
            {checkHistoryQuery.error.message}
          </p>
        )}

        {activeCheckJob &&
          activeCheckJob.id !== workspace?.value.selection.fa && (
            <div>
              <JobProgress job={activeCheckJob} />
              {active(activeCheckJob) && cancel && (
                <button
                  type="button"
                  className="cancel"
                  disabled={cancelling === activeCheckJob.id}
                  onClick={() => cancel(activeCheckJob)}
                >
                  {cancelling === activeCheckJob.id
                    ? "Cancelling…"
                    : "Cancel check"}
                </button>
              )}
              {activeCheckJob.state === "succeeded" &&
                (boundReport ? (
                  <AssessmentReportView
                    key={activeCheckJob.id}
                    report={boundReport}
                  />
                ) : (
                  <p className="error" role="alert">
                    The candidate assessment result could not be verified
                    against this preserved source.
                  </p>
                ))}
            </div>
          )}

        {checkHistoryQuery.data && assessmentRows.length > 0 && (
          <div>
            <h6>Previous candidate assessments</h6>
            <ol
              id={`${id}-assessment-history`}
              className="assessment-history-list"
            >
              {assessmentRows.map((item, index) => (
                <li
                  key={item.id}
                  hidden={
                    !moreAssessments &&
                    index >= 3 &&
                    item.id !== selectedCheckId
                  }
                >
                  <button
                    type="button"
                    id={`${id}-assessment-${item.id}`}
                    className="text-button"
                    aria-current={
                      activeCheckJob?.id === item.id ? "true" : undefined
                    }
                    onClick={() => {
                      checkOp.current?.abort();
                      checkOp.current = null;
                      setCheckWorking("idle");
                      setCheckAttempt((current) =>
                        current?.outcome === "pending"
                          ? {
                              ...current,
                              outcome: "unconfirmed",
                              reason:
                                "The previous request is still unconfirmed. Recover it before retrying.",
                            }
                          : current,
                      );
                      setDiscoveredCheckId(item.id);
                      selectAssessment?.(item.id);
                    }}
                  >
                    {item.title} ({item.id})
                  </button>
                  <span>{item.state}</span>
                  {!checkHistoryQuery.data.jobs.some(
                    (row) => row.id === item.id,
                  ) && <span>Selected from another page</span>}
                </li>
              ))}
            </ol>
            {extraAssessments > 0 && (
              <button
                type="button"
                className="text-button assessment-history-toggle"
                aria-expanded={moreAssessments}
                aria-controls={`${id}-assessment-history`}
                onClick={() => setMoreAssessments((value) => !value)}
              >
                {moreAssessments
                  ? "Fewer candidate assessments"
                  : "More candidate assessments"}{" "}
                · {extraAssessments} additional on this page
              </button>
            )}
            {checkHistoryQuery.data.pages > 1 && (
              <nav
                className="pagination"
                aria-label="Candidate assessment history pages"
              >
                <button
                  type="button"
                  disabled={checkPage <= 1}
                  onClick={() => setCheckPage((p) => Math.max(1, p - 1))}
                >
                  Previous assessment page
                </button>
                <span>
                  Page {checkHistoryQuery.data.page} of{" "}
                  {checkHistoryQuery.data.pages}
                </span>
                <button
                  type="button"
                  disabled={checkPage >= checkHistoryQuery.data.pages}
                  onClick={() => setCheckPage((p) => p + 1)}
                >
                  Next assessment page
                </button>
              </nav>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export function ResumedAssessment({
  source,
  job,
  cancel,
  cancelling,
}: {
  source: Job;
  job: Job;
  cancel?: (job: Job) => void;
  cancelling?: string;
}) {
  const report = extractAssessmentReport(source, job);
  return (
    <section aria-label="Selected book assessment">
      <h3>Recorded assessment</h3>
      <JobProgress job={job} />
      {active(job) && cancel && (
        <button disabled={cancelling === job.id} onClick={() => cancel(job)}>
          Cancel check
        </button>
      )}
      {job.state === "succeeded" &&
        (report ? (
          <AssessmentReportView report={report} level={4} />
        ) : (
          <p className="error" role="alert">
            The recorded assessment could not be verified against this preserved
            source. Clear the selection and choose a fresh assessment.
          </p>
        ))}
    </section>
  );
}
