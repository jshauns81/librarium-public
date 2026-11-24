import { useBookWorkspace } from "./book-workspace";
import React, { useEffect, useId, useRef, useState } from "react";
import { api, ApiError } from "./api";
import {
  decodeCatalogueAuthors,
  type AuthorEvidence,
  type CatalogueComparisonTarget,
} from "./author-groups-api";
import { AliasMatches, AuthorGroups } from "./AuthorGroups";
import { useQuery } from "@tanstack/react-query";
import { CandidateAssessment } from "./CandidateAssessment";
import {
  assessmentJobBinds,
  extractAssessmentReport,
} from "./candidate-assessment-api";
import {
  RawDeclarationValue,
  identifierAssociationLabels,
} from "./IdentifierDeclarations";
import type { Job, IdentifierAssociation, Session } from "./types";
import "./package-comparison.css";

type Snapshot = { version: string; sha256: string; fixture: boolean };
type Person = { id: string; name: string };
type Work = { id: string; title: string; authors: Person[] };
type Listing = {
  author_evidence?: AuthorEvidence;
  snapshot: Snapshot;
  works: Work[];
  total: number;
  page: number;
  page_size: number;
};
type Agreement = "same" | "different" | "partial" | "ambiguous" | "unknown";
type IsbnEvidence = {
  capture: "recorded" | "not_recorded" | "incomplete";
  status: Agreement;
  entries: {
    source: string;
    basis: "urn" | "opf_scheme" | "onix_isbn10" | "onix_isbn13" | null;
    reason_codes: string[];
    source_position: {
      path: string;
      document_sha256: string;
      source_index: number;
    } | null;
    declarations: {
      kind: "opf_scheme" | "identifier_type";
      source_index: number;
      value: string;
      scheme: string | null;
      scheme_iri: string | null;
      refines: string | null;
      association: IdentifierAssociation;
    }[];
    canonical_isbn13: string | null;
    status:
      | "same"
      | "different"
      | "ambiguous"
      | "unknown"
      | "invalid"
      | "unsupported";
    editions: {
      edition_id: string;
      work_id: string | null;
      format: string | null;
      disputed: boolean;
    }[];
  }[];
  scope: string;
};
type AttributionComparison = {
  schema_version: string;
  policy_version: string;
  observation_policy: string | null;
  capture: "recorded" | "unconfirmed" | "not_captured";
  ready: false;
  status: "corroborated" | "conflicting" | "ambiguous" | "unconfirmed";
  job_id: string;
  source_sha256: string;
  report_sha256: string;
  catalogue: Snapshot & { work_id: string };
  observation_ids: string[];
  whole_file_identity: "unconfirmed";
  content_authentication: "unconfirmed";
};
type Comparison = {
  schema_version: string;
  policy_version: string;
  job_id: string;
  source_sha256: string;
  report_sha256: string;
  catalogue: Snapshot & { work_id: string; title: string; authors: Person[] };
  title: { status: Agreement; epub: string[]; catalogue: string };
  creators: {
    status: Agreement;
    epub: string[];
    catalogue: Person[];
    matches: {
      epub_name: string;
      author_id: string | null;
      catalogue_name: string | null;
      basis: "canonical" | "alias" | null;
      status: "same" | "different" | "ambiguous";
    }[];
    missing_authors: Person[];
  };
  isbn: IsbnEvidence;
  source_attribution?: AttributionComparison;
  metadata_agrees: boolean;
  inspection_complete: boolean;
  ready: false;
  scope: string;
};
type Failure = { message: string; snapshot: boolean };
type Load<T> =
  | { state: "idle" }
  | { state: "loading"; previous?: T; failure?: Failure }
  | { state: "loaded"; value: T }
  | ({ state: "error" } & Failure);

function failure(error: unknown): Failure {
  return {
    message:
      error instanceof Error
        ? error.message
        : "The service could not be reached. Retry when it is available.",
    snapshot: error instanceof ApiError && error.status === 409,
  };
}

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const boundedText = (value: unknown): value is string =>
  typeof value === "string" && Array.from(value).length <= 512;
const nullableText = (value: unknown) => value === null || boundedText(value);
const nullableExpandedIri = (value: unknown) =>
  value === null ||
  (typeof value === "string" && Array.from(value).length <= 2 * 512);

const validSourceIndex = (value: unknown) =>
  Number.isInteger(value) &&
  (value as number) >= 0 &&
  (value as number) < 100000;

function validIsbnEvidence(value: unknown): value is IsbnEvidence {
  if (
    !record(value) ||
    !["recorded", "not_recorded", "incomplete"].includes(
      value.capture as string,
    ) ||
    !["same", "different", "partial", "ambiguous", "unknown"].includes(
      value.status as string,
    ) ||
    !boundedText(value.scope) ||
    !Array.isArray(value.entries) ||
    value.entries.length > 64
  )
    return false;
  let references = 0;
  let declarations = 0;
  return value.entries.every((entry) => {
    if (
      !record(entry) ||
      !boundedText(entry.source) ||
      (value.capture === "recorded" && Array.from(entry.source).length > 256) ||
      !(
        entry.basis === null ||
        ["urn", "opf_scheme", "onix_isbn10", "onix_isbn13"].includes(
          entry.basis as string,
        )
      ) ||
      !Array.isArray(entry.reason_codes) ||
      entry.reason_codes.length > 64 ||
      !entry.reason_codes.every(boundedText) ||
      !(
        entry.source_position === null ||
        (record(entry.source_position) &&
          boundedText(entry.source_position.path) &&
          typeof entry.source_position.document_sha256 === "string" &&
          /^[a-f0-9]{64}$/.test(entry.source_position.document_sha256) &&
          validSourceIndex(entry.source_position.source_index))
      ) ||
      !Array.isArray(entry.declarations) ||
      entry.declarations.length > 256 ||
      !entry.declarations.every(
        (declaration) =>
          record(declaration) &&
          ["opf_scheme", "identifier_type"].includes(
            declaration.kind as string,
          ) &&
          validSourceIndex(declaration.source_index) &&
          boundedText(declaration.value) &&
          (value.capture !== "recorded" ||
            declaration.kind === "opf_scheme" ||
            Array.from(declaration.value).length <= 256) &&
          nullableText(declaration.scheme) &&
          nullableExpandedIri(declaration.scheme_iri) &&
          nullableText(declaration.refines) &&
          [
            "identifier",
            "other",
            "ambiguous",
            "unresolved",
            "unsupported",
          ].includes(declaration.association as string),
      ) ||
      (value.capture === "not_recorded" &&
        (entry.source_position !== null ||
          entry.declarations.length > 0 ||
          (entry.basis !== null && entry.basis !== "urn"))) ||
      !(
        entry.canonical_isbn13 === null ||
        (typeof entry.canonical_isbn13 === "string" &&
          /^97[89][0-9]{10}$/.test(entry.canonical_isbn13) &&
          !entry.canonical_isbn13.startsWith("9790"))
      ) ||
      ![
        "same",
        "different",
        "ambiguous",
        "unknown",
        "invalid",
        "unsupported",
      ].includes(entry.status as string) ||
      !Array.isArray(entry.editions) ||
      entry.editions.length > 256
    )
      return false;
    references += entry.editions.length;
    declarations += entry.declarations.length;
    return (
      references <= 256 &&
      declarations <= 256 &&
      entry.editions.every(
        (edition) =>
          record(edition) &&
          boundedText(edition.edition_id) &&
          nullableText(edition.work_id) &&
          nullableText(edition.format) &&
          typeof edition.disputed === "boolean",
      )
    );
  });
}

function samePin(left: Snapshot, right: Snapshot) {
  return (
    left.version === right.version &&
    left.sha256 === right.sha256 &&
    left.fixture === right.fixture
  );
}

export function PackageComparison({
  job,
  session,
  jobs,
  assessmentId,
  selectAssessment,
  onJob,
  cancel,
  cancelling,
  announceTerminal,
  target,
  clearTarget,
}: {
  job: Job;
  session?: Session;
  jobs?: Job[];
  assessmentId?: string;
  selectAssessment?: (id: string) => void;
  onJob?: (job: Job) => void;
  cancel?: (job: Job) => void;
  cancelling?: string;
  announceTerminal?: (jobs: Job[]) => void;
  target?: CatalogueComparisonTarget;
  clearTarget?: () => void;
}) {
  const Panel = assessmentId ? SavedAssessmentPanel : ComparisonPanel;
  return (
    <Panel
      key={`${job.id}:${job.source_sha256}:${job.result.report_sha256}`}
      job={job}
      session={session}
      jobs={jobs}
      assessmentId={assessmentId}
      selectAssessment={selectAssessment}
      onJob={onJob}
      cancel={cancel}
      cancelling={cancelling}
      announceTerminal={announceTerminal}
      target={target}
      clearTarget={clearTarget}
    />
  );
}

function SavedAssessmentPanel(
  props: React.ComponentProps<typeof ComparisonPanel>,
) {
  const { job: source, assessmentId, selectAssessment } = props;
  const saved = useQuery<Job>({
    queryKey: ["candidate-assessment-job", source.id, assessmentId],
    queryFn: async ({ signal }) => {
      const job = await api<Job>(`jobs/${encodeURIComponent(assessmentId!)}`, {
        signal,
      });
      if (job.id !== assessmentId || !assessmentJobBinds(source, job)) {
        throw new Error(
          "The selected assessment does not match this preserved source.",
        );
      }
      return job;
    },
    retry: false,
    refetchInterval: (query) =>
      query.state.data && ["queued", "running"].includes(query.state.data.state)
        ? 1500
        : false,
    structuralSharing: (old, incoming) => {
      const previous = old as Job | undefined;
      const next = incoming as Job;
      return previous && previous.revision > next.revision ? previous : next;
    },
  });
  const report = saved.data
    ? extractAssessmentReport(source, saved.data)
    : null;
  const version = report?.catalogue.version ?? saved.data?.catalogue_version;
  const sha256 = report?.catalogue.sha256 ?? saved.data?.catalogue_sha256;
  const workId =
    report?.file_work_identity.work_id ?? saved.data?.catalogue_work_id;
  return (
    <section aria-label="Selected saved candidate assessment">
      <h3>Selected saved candidate assessment</h3>
      <button
        type="button"
        className="secondary"
        onClick={() => selectAssessment?.("")}
      >
        Back to catalogue comparison
      </button>
      {saved.isPending && <p role="status">Loading saved assessment…</p>}
      {saved.isError && (
        <div role="alert" className="error">
          <p>{saved.error.message}</p>
          <button type="button" onClick={() => void saved.refetch()}>
            Retry saved assessment
          </button>
        </div>
      )}
      {version && sha256 && workId ? (
        <CandidateAssessment
          key={`${source.id}:${assessmentId}:${version}:${sha256}:${workId}`}
          source={source}
          pin={{ version, sha256, fixture: report?.catalogue.fixture ?? false }}
          work={{ id: workId, title: workId }}
          session={props.session}
          jobs={props.jobs}
          assessmentId={assessmentId}
          selectAssessment={selectAssessment}
          onJob={props.onJob}
          cancel={props.cancel}
          cancelling={props.cancelling}
          announceTerminal={props.announceTerminal}
        />
      ) : (
        saved.data && (
          <p>
            This historical record has no complete captured catalogue/work
            selection.
          </p>
        )
      )}
    </section>
  );
}

function ComparisonPanel({
  job,
  session,
  jobs,
  assessmentId,
  selectAssessment,
  onJob,
  cancel,
  cancelling,
  announceTerminal,
  target,
  clearTarget,
}: {
  job: Job;
  session?: Session;
  jobs?: Job[];
  assessmentId?: string;
  selectAssessment?: (id: string) => void;
  onJob?: (job: Job) => void;
  cancel?: (job: Job) => void;
  cancelling?: string;
  announceTerminal?: (jobs: Job[]) => void;
  target?: CatalogueComparisonTarget;
  clearTarget?: () => void;
}) {
  const id = useId();
  const workspace = useBookWorkspace();
  const [open, setOpen] = useState(!!target);
  const [boundTarget, setBoundTarget] = useState(target);
  const [targetWork, setTargetWork] = useState<
    (Work & { author_evidence?: AuthorEvidence }) | null
  >(null);
  const [connection, setConnection] = useState<Load<Snapshot | null>>({
    state: "idle",
  });
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState({ query: "", page: 1 });
  const [listing, setListing] = useState<Load<Listing>>({ state: "idle" });
  const [selected, setSelected] = useState<Work | null>(null);
  const [comparison, setComparison] = useState<Load<Comparison>>({
    state: "idle",
  });
  const statusRequest = useRef<AbortController | null>(null);
  const listingRequest = useRef<AbortController | null>(null);
  const comparisonRequest = useRef<AbortController | null>(null);
  const summary = useRef<HTMLParagraphElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const resultFocus = useRef<{
    from: Element | null;
    controller: AbortController;
  } | null>(null);
  const connectionFocus = useRef<{
    from: Element | null;
    controller: AbortController;
  } | null>(null);
  const listingFocus = useRef<{
    from: Element | null;
    controller: AbortController;
  } | null>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const connectionRetry = useRef<HTMLButtonElement>(null);
  const pin =
    connection.state === "loaded"
      ? connection.value
      : connection.state === "loading"
        ? connection.previous
        : null;
  const connectionFailure =
    connection.state === "error"
      ? connection
      : connection.state === "loading"
        ? connection.failure
        : undefined;
  const results =
    listing.state === "loaded"
      ? listing.value
      : listing.state === "loading"
        ? listing.previous
        : undefined;
  const listingFailure =
    listing.state === "error"
      ? listing
      : listing.state === "loading"
        ? listing.failure
        : undefined;
  const comparisonFailure =
    comparison.state === "error"
      ? comparison
      : comparison.state === "loading"
        ? comparison.failure
        : undefined;

  useEffect(() => {
    if (comparison.state !== "loaded") return;
    const intent = resultFocus.current;
    resultFocus.current = null;
    if (intent && !intent.controller.signal.aborted)
      focusIfStillHere(resultHeading.current, intent.from);
  }, [comparison]);

  useEffect(() => {
    if (connection.state === "idle" || connection.state === "loading") return;
    const intent = connectionFocus.current;
    connectionFocus.current = null;
    if (intent && !intent.controller.signal.aborted)
      focusIfStillHere(
        connection.state === "error"
          ? connectionRetry.current
          : connection.value
            ? searchInput.current
            : null,
        intent.from,
      );
  }, [connection]);
  useEffect(() => {
    if (listing.state !== "loaded") return;
    const intent = listingFocus.current;
    listingFocus.current = null;
    if (intent && !intent.controller.signal.aborted)
      focusIfStillHere(summary.current, intent.from);
  }, [listing]);

  function clearComparison() {
    comparisonRequest.current?.abort();
    setSelected(null);
    setComparison({ state: "idle" });
  }
  function clearSearch() {
    listingRequest.current?.abort();
    setListing({ state: "idle" });
    clearComparison();
  }
  async function connect(useCurrent = false, exactTarget = boundTarget) {
    statusRequest.current?.abort();
    listingRequest.current?.abort();
    comparisonRequest.current?.abort();
    const controller = new AbortController();
    statusRequest.current = controller;
    const from = document.activeElement;
    setConnection((current) => ({
      state: "loading",
      previous: current.state === "loaded" ? current.value : undefined,
      failure: current.state === "error" ? current : undefined,
    }));
    try {
      if (exactTarget && !useCurrent) {
        const parameters = new URLSearchParams({
          version: exactTarget.version,
          sha256: exactTarget.sha256,
        });
        const value = await api<
          Work & { snapshot: Snapshot; author_evidence?: AuthorEvidence }
        >(
          `catalogue/works/${encodeURIComponent(exactTarget.work)}?${parameters}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        const exactPin = {
          version: exactTarget.version,
          sha256: exactTarget.sha256,
          fixture: value.snapshot?.fixture,
        };
        const work = decodeCatalogueAuthors(value, exactPin, {
          work: exactTarget.work,
        });
        clearSearch();
        setTargetWork(work);
        connectionFocus.current = { from, controller };
        setConnection({ state: "loaded", value: exactPin });
        return;
      }
      const result = await api<
        ({ status: "ready" } & Snapshot) | { status: "not_configured" }
      >("catalogue", { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (result.status === "ready") {
        if (useCurrent) {
          setBoundTarget(undefined);
          setTargetWork(null);
          clearTarget?.();
        }
        clearSearch();
        connectionFocus.current = { from, controller };
        setConnection({
          state: "loaded",
          value: {
            version: result.version,
            sha256: result.sha256,
            fixture: result.fixture,
          },
        });
      } else if (result.status === "not_configured") {
        clearSearch();
        setConnection({ state: "loaded", value: null });
      } else {
        throw new Error(
          "The catalogue connection returned an unsupported status.",
        );
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        connectionFocus.current = { from, controller };
        setConnection({ state: "error", ...failure(error) });
      }
    }
  }

  const targetMounted = useRef(false);
  useEffect(() => {
    if (!targetMounted.current) {
      targetMounted.current = true;
      if (target) void connect();
      return;
    }
    if (
      target?.work === boundTarget?.work &&
      target?.version === boundTarget?.version &&
      target?.sha256 === boundTarget?.sha256
    )
      return;
    statusRequest.current?.abort();
    clearSearch();
    setBoundTarget(target);
    setTargetWork(null);
    setConnection({ state: "idle" });
    setOpen(!!target);
    if (target) void connect(false, target);
  }, [target?.work, target?.version, target?.sha256]);

  useEffect(
    () => () => {
      targetMounted.current = false;
      statusRequest.current?.abort();
      listingRequest.current?.abort();
      comparisonRequest.current?.abort();
    },
    [],
  );

  function toggle(next: boolean) {
    setOpen(next);
    if (next && connection.state === "idle") void connect();
    if (!next) {
      statusRequest.current?.abort();
      clearSearch();
      if (connection.state === "loading") setConnection({ state: "idle" });
    }
  }

  function focusIfStillHere(target: HTMLElement | null, from: Element | null) {
    if (
      document.activeElement === from ||
      document.activeElement === document.body
    )
      target?.focus();
  }

  async function search(query: string, page: number) {
    if (!pin || connection.state !== "loaded") return;
    listingRequest.current?.abort();
    clearComparison();
    const controller = new AbortController();
    listingRequest.current = controller;
    const from = document.activeElement;
    setSubmitted({ query, page });
    setListing((current) => ({
      state: "loading",
      previous: current.state === "loaded" ? current.value : undefined,
      failure: current.state === "error" ? current : undefined,
    }));
    try {
      const parameters = new URLSearchParams({
        version: pin.version,
        sha256: pin.sha256,
        q: query,
        page: String(page),
      });
      const result = decodeCatalogueAuthors(
        await api<Listing>(`catalogue/works?${parameters}`, {
          signal: controller.signal,
        }),
        pin,
        { page },
      );
      if (controller.signal.aborted) return;
      if (
        !result.snapshot ||
        !samePin(result.snapshot, pin) ||
        result.page !== page
      )
        throw new Error(
          "The catalogue results do not match the selected snapshot and page.",
        );
      listingFocus.current = { from, controller };
      setListing({ state: "loaded", value: result });
    } catch (error) {
      if (!controller.signal.aborted)
        setListing({ state: "error", ...failure(error) });
    }
  }

  async function compare(work: Work) {
    if (!pin || connection.state !== "loaded") return;
    comparisonRequest.current?.abort();
    resultFocus.current = null;
    const controller = new AbortController();
    comparisonRequest.current = controller;
    const from = document.activeElement;
    setSelected(work);
    setComparison((current) => ({
      state: "loading",
      failure:
        selected?.id === work.id && current.state === "error"
          ? current
          : undefined,
    }));
    try {
      const parameters = new URLSearchParams({
        work: work.id,
        version: pin.version,
        sha256: pin.sha256,
        source_sha256: job.source_sha256 ?? "",
        report_sha256: job.result.report_sha256 ?? "",
      });
      const result = await api<Comparison>(
        `epub-inspections/${encodeURIComponent(job.id)}/comparison?${parameters}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      if (
        result.schema_version !== "librarium.package-comparison.v3" ||
        result.policy_version !== "librarium.package-metadata.v3" ||
        result.job_id !== job.id ||
        result.source_sha256 !== job.source_sha256 ||
        result.report_sha256 !== job.result.report_sha256 ||
        !result.catalogue ||
        result.catalogue.work_id !== work.id ||
        !samePin(result.catalogue, pin) ||
        result.ready !== false
      )
        throw new Error(
          "The comparison does not match this inspection and catalogue selection, so it was not shown.",
        );
      if (!validIsbnEvidence(result.isbn))
        throw new Error(
          "The comparison returned invalid ISBN evidence, so it was not shown.",
        );
      const attribution = result.source_attribution;
      if (
        attribution &&
        (attribution.schema_version !==
          "librarium.source-attribution-comparison.v1" ||
          attribution.policy_version !==
            "librarium.source-attribution-comparison.v1" ||
          attribution.ready !== false ||
          !["recorded", "unconfirmed", "not_captured"].includes(
            attribution.capture,
          ) ||
          attribution.observation_policy !==
            (attribution.capture === "not_captured"
              ? null
              : "librarium.epub-source-attribution.v1") ||
          attribution.job_id !== result.job_id ||
          attribution.source_sha256 !== result.source_sha256 ||
          attribution.report_sha256 !== result.report_sha256 ||
          !attribution.catalogue ||
          !samePin(attribution.catalogue, pin) ||
          attribution.catalogue.work_id !== work.id ||
          !["corroborated", "conflicting", "ambiguous", "unconfirmed"].includes(
            attribution.status,
          ) ||
          attribution.whole_file_identity !== "unconfirmed" ||
          attribution.content_authentication !== "unconfirmed" ||
          !Array.isArray(attribution.observation_ids) ||
          attribution.observation_ids.length > 8 ||
          (attribution.capture !== "recorded" &&
            (attribution.status !== "unconfirmed" ||
              attribution.observation_ids.length !== 0)) ||
          (["corroborated", "conflicting"].includes(attribution.status) &&
            attribution.observation_ids.length !== 1) ||
          (attribution.status === "ambiguous" &&
            !attribution.observation_ids.length) ||
          new Set(attribution.observation_ids).size !==
            attribution.observation_ids.length ||
          attribution.observation_ids.some(
            (id) => typeof id !== "string" || !/^source-title-[1-8]$/.test(id),
          ))
      )
        throw new Error(
          "The source attribution does not match the selected evidence, so it was not shown.",
        );
      resultFocus.current = { from, controller };
      setComparison({ state: "loaded", value: result });
      if (
        workspace &&
        (target?.work !== work.id ||
          target?.version !== pin.version ||
          target?.sha256 !== pin.sha256)
      ) {
        setBoundTarget({
          work: work.id,
          version: pin.version,
          sha256: pin.sha256,
        });
        setTargetWork(work);
        workspace.select({ fcw: work.id, fcv: pin.version, fch: pin.sha256 });
      }
    } catch (error) {
      if (!controller.signal.aborted)
        setComparison({ state: "error", ...failure(error) });
    }
  }

  function recovery(
    error: Failure,
    retry: () => void,
    label: string,
    busy = false,
  ) {
    return (
      <div className="error" role="alert">
        <p>{error.message}</p>
        {error.snapshot && (
          <p>
            The pinned evidence could not be read. You can explicitly choose the
            current catalogue snapshot and search again; the stored inspection
            stays unchanged.
          </p>
        )}
        <div className="actions">
          <button
            ref={
              label === "Retry catalogue connection"
                ? connectionRetry
                : undefined
            }
            type="button"
            aria-disabled={busy}
            onClick={() => {
              if (!busy) retry();
            }}
          >
            {label}
          </button>
          {error.snapshot && (
            <button
              type="button"
              aria-disabled={busy}
              onClick={() => {
                if (!busy) void connect(true);
              }}
            >
              Use current snapshot
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <section className="package-comparison">
      <button
        type="button"
        className="comparison-disclosure"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => toggle(!open)}
      >
        Compare with catalogue
      </button>
      {open && (
        <div id={`${id}-panel`} className="comparison-panel">
          <p className="comparison-intro">
            Choose a catalogue work to compare its title and author credits with
            this EPUB's recorded package metadata. This is a separate read-only
            comparison, calculated now; it is not added to the stored report.
          </p>
          {connection.state === "loading" && (
            <p role="status">Connecting to the catalogue…</p>
          )}
          {connectionFailure &&
            recovery(
              connectionFailure,
              () => void connect(),
              "Retry catalogue connection",
              connection.state === "loading",
            )}
          {connection.state === "loaded" && !pin && (
            <p>
              The catalogue is not configured on this connection. The inspection
              report stays available; a selected catalogue snapshot is needed to
              compare metadata.
            </p>
          )}
          {pin && (
            <>
              <p className="context-note">
                Catalogue snapshot {pin.version}
                {pin.fixture ? " (fictional contract data)" : ""}.
              </p>
              {targetWork && (
                <section aria-label="Selected catalogue work">
                  <h3>{targetWork.title}</h3>
                  <p>
                    {targetWork.authors
                      .map((author) => author.name)
                      .join(", ") || "No author credit recorded"}
                  </p>
                  <AuthorGroups evidence={targetWork.author_evidence} />
                  <button
                    type="button"
                    onClick={() => void compare(targetWork)}
                    disabled={
                      connection.state !== "loaded" ||
                      comparison.state === "loading"
                    }
                  >
                    Compare selected catalogue work
                  </button>
                </section>
              )}
              <form
                className="comparison-search"
                onSubmit={(event) => {
                  event.preventDefault();
                  void search(draft.trim(), 1);
                }}
              >
                <label htmlFor={`${id}-query`}>
                  Search catalogue titles or authors
                </label>
                <div className="comparison-search-controls">
                  <input
                    ref={searchInput}
                    id={`${id}-query`}
                    type="search"
                    maxLength={200}
                    value={draft}
                    onChange={(event) => {
                      setDraft(event.target.value);
                      clearSearch();
                    }}
                  />
                  <button
                    type="submit"
                    aria-disabled={connection.state === "loading"}
                  >
                    Search catalogue
                  </button>
                </div>
              </form>
              {listing.state === "loading" && (
                <p role="status">
                  Searching catalogue titles and recorded author spellings…
                </p>
              )}
              {listingFailure &&
                recovery(
                  listingFailure,
                  () => void search(submitted.query, submitted.page),
                  "Retry catalogue search",
                  listing.state === "loading" || connection.state === "loading",
                )}
              {results && (
                <>
                  <AliasMatches evidence={results.author_evidence} />
                  <AuthorGroups evidence={results.author_evidence} />
                  <p ref={summary} tabIndex={-1} className="comparison-summary">
                    {results.total
                      ? `${results.total.toLocaleString()} catalogue ${results.total === 1 ? "work" : "works"}. Page ${results.page} of ${Math.ceil(results.total / results.page_size)}.`
                      : "No catalogue works match this search. Try another title, recorded author spelling or a shorter search."}
                  </p>
                  <ul
                    className="comparison-choices"
                    aria-label="Catalogue works to compare"
                  >
                    {results.works.map((work) => (
                      <li key={work.id}>
                        <div>
                          <p className="comparison-work-title">{work.title}</p>
                          <p className="comparison-authors">
                            {work.authors
                              .map((person) => person.name)
                              .join(", ") || "No author credit recorded"}
                          </p>
                        </div>
                        <button
                          type="button"
                          aria-label={`Compare ${work.title}`}
                          aria-pressed={selected?.id === work.id}
                          disabled={
                            listing.state === "loading" ||
                            connection.state === "loading"
                          }
                          onClick={() => void compare(work)}
                        >
                          Compare
                        </button>
                      </li>
                    ))}
                  </ul>
                  {results.total > results.page_size && (
                    <nav
                      className="actions comparison-pages"
                      aria-label="Catalogue result pages"
                    >
                      <button
                        type="button"
                        aria-label="Previous catalogue results"
                        disabled={results.page <= 1}
                        aria-disabled={
                          listing.state === "loading" ||
                          connection.state === "loading"
                        }
                        onClick={() =>
                          listing.state !== "loading" &&
                          connection.state === "loaded" &&
                          void search(submitted.query, submitted.page - 1)
                        }
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        aria-label="Next catalogue results"
                        disabled={
                          results.page * results.page_size >= results.total
                        }
                        aria-disabled={
                          listing.state === "loading" ||
                          connection.state === "loading"
                        }
                        onClick={() =>
                          listing.state !== "loading" &&
                          connection.state === "loaded" &&
                          void search(submitted.query, submitted.page + 1)
                        }
                      >
                        Next
                      </button>
                    </nav>
                  )}
                </>
              )}
              {comparison.state === "loading" && (
                <p role="status">
                  Comparing package metadata with {selected?.title}…
                </p>
              )}
              {comparisonFailure &&
                selected &&
                recovery(
                  comparisonFailure,
                  () => void compare(selected),
                  "Retry comparison",
                  comparison.state === "loading" ||
                    connection.state === "loading",
                )}
              {comparison.state === "loaded" && (
                <>
                  <ComparisonResult
                    value={comparison.value}
                    heading={resultHeading}
                  />
                  <CandidateAssessment
                    key={`assessment:${job.id}:${pin.version}:${pin.sha256}:${comparison.value.catalogue.work_id}`}
                    source={job}
                    pin={pin}
                    work={{
                      id: comparison.value.catalogue.work_id,
                      title: comparison.value.catalogue.title,
                    }}
                    session={session}
                    jobs={jobs}
                    assessmentId={assessmentId}
                    selectAssessment={selectAssessment}
                    onJob={onJob}
                    cancel={cancel}
                    cancelling={cancelling}
                    announceTerminal={announceTerminal}
                  />
                </>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

const titleLabels: Record<Agreement, string> = {
  same: "Title agrees",
  different: "Title differs",
  partial: "Title partly agrees",
  ambiguous: "More than one package title",
  unknown: "Title not compared",
};
const creatorLabels: Record<Agreement, string> = {
  same: "Creator names agree",
  different: "Creator names differ",
  partial: "Some creator names agree",
  ambiguous: "Creator names are ambiguous",
  unknown: "Creator names not compared",
};

function ComparisonResult({
  value,
  heading,
}: {
  value: Comparison;
  heading: React.RefObject<HTMLHeadingElement | null>;
}) {
  const id = useId();
  return (
    <section
      className="comparison-result"
      aria-label="Package metadata comparison"
    >
      <h3 ref={heading} tabIndex={-1} className="comparison-work-title">
        {value.catalogue.title}
      </h3>
      <p className="comparison-verdict">
        {value.metadata_agrees
          ? "The recorded title and creator names agree."
          : "Read the title and creator evidence below before drawing a conclusion."}
      </p>
      {!value.inspection_complete && (
        <p className="comparison-caution">
          The inspection stopped before reading the whole archive. Metadata
          agreement was not assessed from the incomplete report.
        </p>
      )}
      {value.source_attribution && (
        <section aria-labelledby={`${id}-source-title`}>
          <h4 id={`${id}-source-title`}>
            Source attribution: {value.source_attribution.status}
          </h4>
          <p>
            Source title and credit labels are compared separately from package
            metadata. Whole-file identity remains unconfirmed.
          </p>
          {value.source_attribution.observation_ids.length > 0 && (
            <p className="context-note">
              Source observations:{" "}
              {value.source_attribution.observation_ids.join(", ")}
            </p>
          )}
        </section>
      )}
      <section aria-labelledby={`${id}-title`}>
        <h4 id={`${id}-title`}>{titleLabels[value.title.status]}</h4>
        <dl className="comparison-values">
          <div>
            <dt>EPUB package titles</dt>
            <dd>
              <Values values={value.title.epub} />
            </dd>
          </div>
          <div>
            <dt>Catalogue title</dt>
            <dd>{value.title.catalogue || "Not recorded"}</dd>
          </div>
        </dl>
      </section>
      <section aria-labelledby={`${id}-creators`}>
        <h4 id={`${id}-creators`}>{creatorLabels[value.creators.status]}</h4>
        <p className="context-note">
          EPUB creator names / catalogue author credits
        </p>
        <dl className="comparison-values">
          <div>
            <dt>EPUB creator names</dt>
            <dd>
              <Values values={value.creators.epub} />
            </dd>
          </div>
          <div>
            <dt>Catalogue author credits</dt>
            <dd>
              <Values
                values={value.creators.catalogue.map((person) => person.name)}
              />
            </dd>
          </div>
        </dl>
        {!!value.creators.matches.length && (
          <ul
            className="comparison-name-evidence"
            aria-label="Creator name evidence"
          >
            {value.creators.matches.map((match, index) => (
              <li key={index}>
                <span>{match.epub_name}</span>
                <span className="context-note">
                  {match.status === "ambiguous"
                    ? "This spelling belongs to more than one recorded author."
                    : match.status === "different"
                      ? "No unique match to this work's author credits."
                      : match.basis === "alias"
                        ? `Recorded alias of ${match.catalogue_name}`
                        : `Recorded canonical name: ${match.catalogue_name}`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {!!value.creators.missing_authors.length && (
          <p>
            Catalogue authors not covered:{" "}
            {value.creators.missing_authors
              .map((person) => person.name)
              .join(", ")}
          </p>
        )}
      </section>
      <IsbnEvidenceResult value={value.isbn} workId={value.catalogue.work_id} />
      <p className="comparison-caution">{value.scope}</p>
      <details className="comparison-provenance">
        <summary>Comparison provenance</summary>
        <dl className="provenance">
          <dt>Comparison policy</dt>
          <dd>{value.policy_version}</dd>
          <dt>Catalogue version</dt>
          <dd>{value.catalogue.version}</dd>
          <dt>Catalogue fingerprint</dt>
          <dd className="hash">{value.catalogue.sha256}</dd>
          <dt>Source digest</dt>
          <dd className="hash">{value.source_sha256}</dd>
          <dt>Report digest</dt>
          <dd className="hash">{value.report_sha256}</dd>
        </dl>
      </details>
    </section>
  );
}

const isbnLabels: Record<Agreement, string> = {
  same: "ISBN evidence agrees with the selected work",
  different: "ISBN evidence points to another work",
  partial: "ISBN evidence partly agrees",
  ambiguous: "ISBN evidence is ambiguous",
  unknown: "ISBN evidence is unknown",
};
const isbnEntryLabels: Record<
  IsbnEvidence["entries"][number]["status"],
  string
> = {
  same: "Recorded for the selected work",
  different: "Recorded for another work",
  ambiguous: "Ambiguous catalogue evidence",
  unknown: "ISBN evidence unknown",
  invalid: "Invalid declared ISBN",
  unsupported: "Unsupported identifier",
};

const isbnBasisLabels = {
  urn: "Explicit ISBN URN",
  opf_scheme: "OPF ISBN scheme",
  onix_isbn10: "ONIX ISBN10 declaration",
  onix_isbn13: "ONIX ISBN13 declaration",
};
const isbnReasonLabels: Record<string, string> = {
  identifier_not_text:
    "The identifier contains nested markup and was not assessed as plain ISBN text.",
  isbn_not_declared: "No supported ISBN declaration was recorded.",
  urn_components_unassessed: "Additional URN components were not assessed.",
  invalid_isbn: "The declared ISBN has an invalid length or checksum.",
  unsupported_opf_scheme:
    "The OPF scheme is not supported for ISBN assessment.",
  unsupported_scheme_version: "This scheme version is not supported.",
  unsupported_identifier_type_scheme:
    "The identifier type scheme is not supported.",
  unsupported_identifier_type_code:
    "The identifier type code is not supported for ISBN assessment.",
  identifier_type_not_text: "The type record contains nested markup.",
  identifier_type_target_ambiguous:
    "The type record has more than one possible target.",
  identifier_type_target_unresolved:
    "The type record target could not be resolved.",
  multiple_identifier_types:
    "Multiple identifier type records prevent a unique assessment.",
  conflicting_identifier_declarations:
    "The recorded identifier declarations conflict.",
  isbn_type_length_mismatch:
    "The ISBN length conflicts with its declared type.",
  prefix_declaration_invalid:
    "The prefix declaration could not be resolved for this assessment.",
  legacy_declarations_not_captured:
    "Identifier attributes and type records were not captured by this historical inspection.",
  inspection_incomplete:
    "The inspection did not capture complete identifier evidence.",
};

function IsbnEvidenceResult({
  value,
  workId,
}: {
  value: IsbnEvidence;
  workId: string;
}) {
  const id = useId();
  return (
    <section className="comparison-isbn" aria-labelledby={`${id}-isbn`}>
      <h4 id={`${id}-isbn`}>ISBN evidence</h4>
      <p className="comparison-isbn-verdict">
        <strong>{isbnLabels[value.status]}</strong>
      </p>
      <p className="comparison-caution">{value.scope}</p>
      {value.capture === "not_recorded" && (
        <p className="context-note">
          Identifier attributes and type records were not recorded by this
          inspection. Legacy explicit ISBN URNs can still be assessed.
        </p>
      )}
      {value.capture === "incomplete" && (
        <p className="context-note">
          The inspection was incomplete; ISBN declarations were not fully
          assessed.
        </p>
      )}
      {value.entries.length ? (
        <ol className="comparison-isbn-entries">
          {value.entries.map((entry, index) => (
            <li key={index}>
              <p className="comparison-isbn-status">
                {isbnEntryLabels[entry.status]}
              </p>
              <p className="comparison-isbn-basis">
                Basis:{" "}
                {entry.basis === null
                  ? "No supported declaration assessed"
                  : isbnBasisLabels[entry.basis]}
              </p>
              {entry.reason_codes.length > 0 && (
                <ul className="comparison-isbn-reasons">
                  {entry.reason_codes.map((code, i) => (
                    <li key={i}>
                      {Object.hasOwn(isbnReasonLabels, code)
                        ? isbnReasonLabels[code]
                        : `Recorded reason: ${code}`}
                    </li>
                  ))}
                </ul>
              )}
              <dl className="comparison-values">
                <div>
                  <dt>Recorded package identifier</dt>
                  <dd>
                    <bdi className="comparison-identifier">
                      {entry.source || "Empty identifier"}
                    </bdi>
                  </dd>
                </div>
                <div>
                  <dt>Canonical ISBN13</dt>
                  <dd>
                    {entry.canonical_isbn13 === null ? (
                      "Not available"
                    ) : (
                      <bdi>{entry.canonical_isbn13}</bdi>
                    )}
                  </dd>
                </div>
              </dl>
              {(entry.declarations.length > 0 ||
                entry.source_position !== null) && (
                <details className="comparison-isbn-editions">
                  <summary>
                    Identifier declarations (
                    {entry.declarations.length.toLocaleString()})
                  </summary>
                  {entry.source_position && (
                    <>
                      <p>
                        Package source index{" "}
                        {entry.source_position.source_index}
                      </p>
                      <dl className="comparison-values">
                        <div>
                          <dt>Package document</dt>
                          <dd>
                            <bdi>{entry.source_position.path}</bdi>
                          </dd>
                        </div>
                        <div>
                          <dt>Package byte digest</dt>
                          <dd>{entry.source_position.document_sha256}</dd>
                        </div>
                      </dl>
                    </>
                  )}
                  <ul>
                    {entry.declarations.map((declaration, position) => (
                      <li key={position}>
                        <p>
                          <strong>
                            {declaration.kind === "opf_scheme"
                              ? "OPF scheme attribute"
                              : "Identifier type record"}
                          </strong>{" "}
                          · package source index {declaration.source_index}
                        </p>
                        <p>
                          {identifierAssociationLabels[declaration.association]}
                        </p>
                        <dl className="comparison-values">
                          <div>
                            <dt>Recorded value</dt>
                            <dd>
                              <RawDeclarationValue value={declaration.value} />
                            </dd>
                          </div>
                          <div>
                            <dt>scheme</dt>
                            <dd>
                              <RawDeclarationValue value={declaration.scheme} />
                            </dd>
                          </div>
                          <div>
                            <dt>Resolved scheme IRI</dt>
                            <dd>
                              <RawDeclarationValue
                                value={declaration.scheme_iri}
                              />
                            </dd>
                          </div>
                          <div>
                            <dt>refines</dt>
                            <dd>
                              <RawDeclarationValue
                                value={declaration.refines}
                              />
                            </dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {entry.editions.length > 0 && (
                <details className="comparison-isbn-editions">
                  <summary>
                    Matched catalogue editions (
                    {entry.editions.length.toLocaleString()})
                  </summary>
                  <ul>
                    {entry.editions.map((edition, position) => (
                      <li key={position}>
                        <p className="comparison-isbn-edition-status">
                          <span>
                            {edition.work_id === null
                              ? "Work not assigned"
                              : edition.work_id === workId
                                ? "Selected work"
                                : "Other work"}
                          </span>
                          {edition.disputed && <span>Disputed</span>}
                        </p>
                        <dl className="comparison-values">
                          <div>
                            <dt>Edition ID</dt>
                            <dd>
                              <bdi>
                                {edition.edition_id || "Empty edition ID"}
                              </bdi>
                            </dd>
                          </div>
                          <div>
                            <dt>Work ID</dt>
                            <dd>
                              {edition.work_id === null ? (
                                "Not assigned"
                              ) : (
                                <bdi>{edition.work_id || "Empty work ID"}</bdi>
                              )}
                            </dd>
                          </div>
                          <div>
                            <dt>Format</dt>
                            <dd>
                              {edition.format === null ? (
                                "Not recorded"
                              ) : (
                                <bdi>{edition.format || "Empty format"}</bdi>
                              )}
                            </dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p>No package identifiers were recorded for this assessment.</p>
      )}
    </section>
  );
}

function Values({ values }: { values: string[] }) {
  return values.length ? (
    <ul>
      {values.map((value, index) => (
        <li key={index}>{value || "Empty"}</li>
      ))}
    </ul>
  ) : (
    <>Not recorded</>
  );
}
