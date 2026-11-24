import React, { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { api, ApiError } from "./api";
import {
  intentKey,
  mergeJobs,
  createTerminalAnnouncer,
  commandNotice,
} from "./state";
import type { Collection, Job, Session, Work } from "./types";
import {
  Library,
  defaultLibraryOrder,
  type LibraryReturn,
  type CatalogueSelection,
  type LibraryWork,
} from "./Library";
import {
  Catalogue,
  catalogueContextKey,
  type CatalogueReturn,
} from "./Catalogue";
import { JobProgress, stateLabel } from "./JobProgress";
import { ArchivistMark, LibrariumWordmark } from "./Identity";
import { ThemePicker } from "./ThemePicker";
import {
  ReviewHistory,
  historyKinds,
  reviewStates,
  type HistoryKind,
  type ReviewReturn,
} from "./ReviewHistory";
import { clearWorkspace, resolveWorkspace } from "./book-workspace";
import { isRetiredKind, RETIRED_KINDS } from "./retired-kinds";
import { FileInspections, type FileReturn } from "./FileInspections";
import { Home } from "./Home";
import { Settings } from "./Settings";
import "./shell.css";
import { useThemeSync } from "./theme-sync";
import {
  DirectLibrary,
  type DirectLibraryBook,
  type DirectLibraryInventory,
} from "./DirectLibrary";
import { CatalogueControl } from "./CatalogueControl";
import { CatalogueHealth } from "./CatalogueHealth";
import { trackReturnIntent } from "./return-intent";
import { CoverReview } from "./CoverReview";

type CommandFocus = {
  restoreFocus: boolean | undefined;
  element: Element | null;
  view: string;
  work: string;
  requestKey?: string;
};
type CatalogueComparisonReturn = {
  work: string;
  version: string;
  sha256: string;
  scroll: number;
  paneScroll: number;
  disclosures?: boolean[];
  libraryOrigin?: LibraryReturn;
  reviewOrigin?: ReviewReturn;
  catalogueReturn?: CatalogueReturn;
};

const live = (job: Job) => ["queued", "running"].includes(job.state);
export function parameters() {
  const p = new URLSearchParams(location.search);
  const selection = (key: string) =>
    p.getAll(key).length > 1
      ? "invalid-duplicate-selection"
      : (p.get(key) ?? "");
  return {
    q: p.get("q") ?? "",
    series: p.get("series") ?? "",
    page: Math.max(1, Number(p.get("page")) || 1),
    work: p.get("work") ?? "",
    view: [
      "home",
      "settings",
      "inspections",
      "catalogue",
      "files",
      "covers",
    ].includes(p.get("view") ?? "")
      ? p.get("view")!
      : "collection",
    cq: p.get("cq") ?? "",
    cp: Math.max(1, Number(p.get("cp")) || 1),
    cw: p.get("cw") ?? "",
    cv: p.get("cv") ?? "",
    ch: p.get("ch") ?? "",
    cs: p.get("cs") ?? "",
    cb: p.get("cb") === "series" ? "series" : "works",
    ca: p.get("ca") ?? "",
    cm: ["browse", "operations", "health"].includes(p.get("cm") ?? "")
      ? p.get("cm")!
      : "browse",
    cc: p.get("cc") ?? "incomplete",
    ccp: Math.max(1, Math.min(10000, Number(p.get("ccp")) || 1)),
    lq: p.get("lq") ?? "",
    lp: Math.max(1, Number(p.get("lp")) || 1),
    lo: p.get("lo") ?? "owned",
    lx: ["series", "title", "author"].includes(p.get("lx") ?? "")
      ? p.get("lx")!
      : defaultLibraryOrder(),
    lt: p.get("lt") ?? "",
    lw: p.get("lw") ?? "",
    lwp: Math.min(10000, Math.max(1, Math.floor(Number(p.get("lwp")) || 1))),
    ls: p.get("ls") ?? "",
    ld: p.get("ld") === "1" ? "1" : "",
    lg: p.get("lg") === "standalone" ? "standalone" : "",
    crs: ["done", "skipped"].includes(p.get("crs") ?? "") ? p.get("crs")! : "",
    crr: [
      "missing",
      "generated",
      "small",
      "blank",
      "width_below_1000",
      "height_below_1200",
      "unresolved",
    ].includes(p.get("crr") ?? "")
      ? p.get("crr")!
      : "",
    crp: Math.min(10000, Math.max(1, Math.floor(Number(p.get("crp")) || 1))),
    rq: (p.get("rq") ?? "").slice(0, 200),
    rs: reviewStates.includes(p.get("rs") ?? "") ? p.get("rs")! : "",
    rp: Math.min(10000, Math.max(1, Math.floor(Number(p.get("rp")) || 1))),
    rk: historyKinds.includes(p.get("rk") ?? "")
      ? p.get("rk")!
      : (RETIRED_KINDS as readonly string[]).includes(p.get("rk") ?? "")
        ? "retired"
        : "",
    rj: p.get("rj") ?? "",
    fj: selection("fj"),
    fv: selection("fv"),
    // Older links pinned the assessment a review copy or delivery used; that pin
    // came first then, so it still chooses the assessment now.
    fa: selection("faj") || selection("fda") || selection("fa"),
    fcw: p.get("fcw") ?? "",
    fcv: p.get("fcv") ?? "",
    fch: p.get("fch") ?? "",
    fq: (p.get("fq") ?? "").slice(0, 200),
    fs: reviewStates.includes(p.get("fs") ?? "") ? p.get("fs")! : "",
    fp: Math.min(10000, Math.max(1, Math.floor(Number(p.get("fp")) || 1))),
  };
}

export function App() {
  const [route, setRoute] = useState(parameters);
  const [desktopMasthead, setDesktopMasthead] = useState(
    () =>
      typeof matchMedia !== "function" ||
      matchMedia("(min-width: 960px) and (min-height: 680px)").matches,
  );
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const media = matchMedia("(min-width: 960px) and (min-height: 680px)");
    const changed = () => setDesktopMasthead(media.matches);
    media.addEventListener?.("change", changed);
    return () => media.removeEventListener?.("change", changed);
  }, []);
  const currentRoute = useRef(route);
  currentRoute.current = route;
  const latestRequests = useRef(new Map<string, string>());
  const nativeRequests = useRef(new Map<string, string>());
  const [search, setSearch] = useState(route.q);
  const queryClient = useQueryClient();
  const focusReturn = useRef("");
  const scrollReturn = useRef(0);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const selectionIntent = useRef<"list" | "history" | null>(null);
  const [notice, setNotice] = useState("");
  const [selectionAnnouncement, setSelectionAnnouncement] = useState("");
  const [jobAnnouncement, setJobAnnouncement] = useState("");
  const [announceTerminal] = useState(() =>
    createTerminalAnnouncer(setJobAnnouncement),
  );
  const [refreshing, setRefreshing] = useState(false);
  const [pollClock, setPollClock] = useState(Date.now);
  const session = useQuery({
    queryKey: ["session"],
    queryFn: ({ signal }) => api<Session>("session", { signal }),
    retry: false,
    staleTime: Infinity,
    refetchInterval: (query) =>
      query.state.error &&
      (!(query.state.error instanceof ApiError) ||
        query.state.error.status >= 500)
        ? 1500
        : false,
  });
  const realLibrary = !!session.data?.library;
  const nativeLibrary = !!session.data?.direct_library;
  const fileInspections = !!session.data?.file_inspections;
  useThemeSync();
  // The plain address opens on Home, the lit room, once the library is known.
  const landed = useRef(location.search === "");
  useEffect(() => {
    if (landed.current && nativeLibrary) {
      landed.current = false;
      navigate({ view: "home" });
    }
  }, [nativeLibrary]);
  const liveFileJobs = (
    queryClient.getQueryData<{ jobs: Job[] }>(["jobs", "epub"])?.jobs ?? []
  ).some(live);
  const fileJobs = useQuery<{ jobs: Job[] }>({
    queryKey: ["jobs", "epub"],
    enabled: !!session.data && (route.view === "files" || liveFileJobs),
    queryFn: ({ signal }) => api("jobs?kind=epub", { signal }),
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
  const liveValidationJobs = (
    queryClient.getQueryData<{ jobs: Job[] }>(["jobs", "epub_validation"])
      ?.jobs ?? []
  ).some(live);
  const validationJobs = useQuery<{ jobs: Job[] }>({
    queryKey: ["jobs", "epub_validation"],
    enabled:
      !!session.data &&
      (session.data.epub_validation === true || liveValidationJobs),
    queryFn: ({ signal }) => api("jobs?kind=epub_validation", { signal }),
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
  const jobs = useQuery<{ jobs: Job[] }>({
    queryKey: ["jobs", route.work, "all"],
    enabled:
      !!session.data &&
      (realLibrary ||
        route.view === "inspections" ||
        route.view === "catalogue" ||
        (route.view === "collection" && !realLibrary)),
    queryFn: ({ signal }) =>
      api(`jobs?work_id=${encodeURIComponent(route.work)}`, { signal }),
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
  const collection = useQuery({
    queryKey: ["works", route.q, route.series, route.page],
    enabled: route.view === "collection" && !realLibrary,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      api<Collection>(
        `works?${new URLSearchParams({ q: route.q, series: route.series, page: String(route.page) })}`,
        { signal },
      ),
  });
  const detail = useQuery({
    queryKey: ["work", route.work],
    queryFn: ({ signal }) =>
      api<Work>(`works/${encodeURIComponent(route.work)}`, { signal }),
    enabled: !!route.work && route.view === "collection" && !realLibrary,
  });

  function nativeOrigin() {
    const current = currentRoute.current;
    const captured = queryClient.getQueryData<{ book: DirectLibraryBook }>([
      "direct-library",
      "book",
      current.lw,
      current.lt,
    ])?.book;
    return {
      route: {
        lq: current.lq,
        lp: current.lp,
        lt: current.lt,
        lw: current.lw,
        ld: current.ld,
        lwp: current.lwp,
      },
      scroll: window.scrollY,
      focusId: document.activeElement?.id,
      book: captured,
    };
  }
  function openNativeWorkspace(source: string) {
    const origin = nativeOrigin();
    history.replaceState({ ...history.state, nativeLibraryReturn: origin }, "");
    navigate(
      {
        view: "files",
        fj: source,
        ...clearWorkspace,
        fcw: "",
        fcv: "",
        fch: "",
      },
      true,
      { nativeLibraryOrigin: origin },
    );
    window.scrollTo(0, 0);
  }
  function returnToNativeLibrary() {
    const origin = history.state?.nativeLibraryOrigin;
    if (origin)
      navigate({ view: "collection", ...origin.route }, true, {
        nativeLibraryReturn: origin,
      });
  }
  function browseBookReferences() {
    const origin = {
      route: currentRoute.current,
      scroll: window.scrollY,
      focusId: document.activeElement?.id,
    };
    history.replaceState({ ...history.state, bookWorkspaceReturn: origin }, "");
    navigate(
      { view: "catalogue", cm: "browse", cw: "", cs: "", ca: "", cq: "" },
      true,
      { bookWorkspaceOrigin: origin },
    );
    window.scrollTo(0, 0);
  }
  function returnToBookWorkspace() {
    const origin = history.state?.bookWorkspaceOrigin;
    if (origin)
      navigate(origin.route, true, {
        bookWorkspaceReturn: origin,
        nativeLibraryOrigin: history.state?.nativeLibraryOrigin,
        reviewOrigin: history.state?.reviewOrigin,
      });
  }
  function navigate(
    next: Partial<typeof route>,
    push = false,
    state: unknown = null,
  ) {
    const sourceChanged =
      next.fj !== undefined && next.fj !== currentRoute.current.fj;
    const value = {
      ...currentRoute.current,
      ...(sourceChanged
        ? { ...clearWorkspace, fcw: "", fcv: "", fch: "" }
        : {}),
      ...next,
      // A link into a work, series, author or search opens the books, not tool health.
      ...(next.view === "catalogue" &&
      next.cm === undefined &&
      (next.cw || next.cs || next.ca || next.cq)
        ? { cm: "browse" }
        : {}),
    };
    currentRoute.current = value;
    const params = new URLSearchParams();
    Object.entries(value).forEach(([key, val]) => {
      if (val && val !== 1 && !(key === "view" && val === "collection"))
        params.set(key, String(val));
    });
    const nativeLibraryOrigin =
      !sourceChanged && ["files", "catalogue"].includes(value.view)
        ? history.state?.nativeLibraryOrigin
        : null;
    const bookWorkspaceOrigin =
      !sourceChanged && value.view === "catalogue"
        ? history.state?.bookWorkspaceOrigin
        : null;
    const origin =
      value.view === "catalogue" ? history.state?.libraryOrigin : null;
    const reviewOrigin =
      !sourceChanged &&
      (value.view === "catalogue" ||
        (value.view === "files" && value.fj) ||
        (value.view === "collection" && value.work && !realLibrary))
        ? history.state?.reviewOrigin
        : null;
    const fileOrigin =
      !sourceChanged && value.view === "files" && value.fj
        ? history.state?.fileOrigin
        : null;
    const comparisonOrigin =
      !sourceChanged && value.view === "files"
        ? history.state?.catalogueComparisonOrigin
        : null;
    const catalogueReturn =
      value.view === "catalogue" &&
      history.state?.catalogueReturn?.context === catalogueContextKey(value)
        ? history.state.catalogueReturn
        : null;
    history[push ? "pushState" : "replaceState"](
      nativeLibraryOrigin ||
        bookWorkspaceOrigin ||
        origin ||
        reviewOrigin ||
        fileOrigin ||
        comparisonOrigin ||
        catalogueReturn
        ? {
            ...(nativeLibraryOrigin ? { nativeLibraryOrigin } : {}),
            ...(bookWorkspaceOrigin ? { bookWorkspaceOrigin } : {}),
            ...(origin ? { libraryOrigin: origin } : {}),
            ...(reviewOrigin ? { reviewOrigin } : {}),
            ...(fileOrigin ? { fileOrigin } : {}),
            ...(catalogueReturn ? { catalogueReturn } : {}),
            ...(comparisonOrigin
              ? { catalogueComparisonOrigin: comparisonOrigin }
              : {}),
            ...(state && typeof state === "object" ? state : {}),
          }
        : state,
      "",
      `${location.pathname}?${params}`,
    );
    setRoute(value);
  }
  function compareCatalogueSource(
    work: string,
    version: string,
    sha256: string,
  ) {
    const disclosures = Array.from(
      document.querySelectorAll<HTMLDetailsElement>(".catalogue details"),
      (element) => element.open,
    );
    const origin: CatalogueComparisonReturn = {
      work,
      version,
      sha256,
      scroll: Math.max(0, window.scrollY),
      paneScroll: Math.max(
        0,
        document.querySelector<HTMLElement>(".catalogue .detail")?.scrollTop ??
          0,
      ),
      disclosures: disclosures.length <= 256 ? disclosures : undefined,
      libraryOrigin: history.state?.libraryOrigin,
      reviewOrigin: history.state?.reviewOrigin,
      catalogueReturn: history.state?.catalogueReturn,
    };
    const bookOrigin = history.state?.bookWorkspaceOrigin;
    if (bookOrigin) {
      navigate(
        {
          ...bookOrigin.route,
          view: "files",
          fcw: work,
          fcv: version,
          fch: sha256,
        },
        true,
        {
          bookWorkspaceReturn: bookOrigin,
          catalogueComparisonOrigin: origin,
          nativeLibraryOrigin: history.state?.nativeLibraryOrigin,
          reviewOrigin: history.state?.reviewOrigin,
        },
      );
      return;
    }
    navigate(
      {
        view: "files",
        fj: "",
        fv: "",
        fa: "",
        fcw: work,
        fcv: version,
        fch: sha256,
      },
      true,
      { catalogueComparisonOrigin: origin },
    );
  }
  function returnToCatalogueWork() {
    const origin = history.state?.catalogueComparisonOrigin as
      CatalogueComparisonReturn | undefined;
    navigate({ view: "catalogue", cm: "browse" }, true, {
      ...(origin?.libraryOrigin ? { libraryOrigin: origin.libraryOrigin } : {}),
      ...(origin?.reviewOrigin ? { reviewOrigin: origin.reviewOrigin } : {}),
      ...(origin?.catalogueReturn
        ? { catalogueReturn: origin.catalogueReturn }
        : {}),
      catalogueComparisonReturn: origin ?? {
        work: route.cw,
        version: route.cv,
        sha256: route.ch,
        scroll: 0,
        paneScroll: 0,
      },
    });
  }
  function openCatalogue(selection: CatalogueSelection, origin: LibraryReturn) {
    history.replaceState({ ...history.state, libraryReturn: origin }, "");
    navigate(
      {
        view: "catalogue",
        cq: "",
        cp: 1,
        cw: "",
        cs: "",
        ca: "",
        cb: "works",
        ...selection,
      },
      true,
      { libraryOrigin: origin },
    );
    window.scrollTo(0, 0);
  }
  function returnToLibrary() {
    const origin: LibraryReturn | undefined = history.state?.libraryOrigin;
    if (!origin) return;
    navigate({ view: "collection", ...origin.route, ld: "" }, true, {
      libraryReturn: origin,
    });
  }
  async function inspectLibraryBook(
    book: DirectLibraryBook,
    inventory: DirectLibraryInventory,
  ) {
    if (!session.data)
      throw new Error("Connection is not ready. Retry the connection first.");
    const target = `direct-library:${book.id}:${inventory.token}`;
    let key = nativeRequests.current.get(target);
    if (!key) {
      try {
        key = intentKey(localStorage, target);
      } catch {
        key = crypto.randomUUID();
      }
      nativeRequests.current.set(target, key);
    }
    const job = await api<Job>(
      `direct-library/books/${encodeURIComponent(book.id)}/inspect`,
      {
        method: "POST",
        headers: { "X-CSRFToken": session.data.csrf, "Idempotency-Key": key },
        body: JSON.stringify({ inventory: inventory.token }),
      },
    );
    merge(job);
    nativeRequests.current.delete(target);
    try {
      if (localStorage.getItem(`librarium-intent:${target}`) === key)
        localStorage.removeItem(`librarium-intent:${target}`);
    } catch {
      /* The in-memory request key already preserved this attempt. */
    }
    if (
      currentRoute.current.view === "collection" &&
      currentRoute.current.lw === book.id &&
      currentRoute.current.lt === inventory.token
    ) {
      openNativeWorkspace(job.id);
      window.scrollTo(0, 0);
    }
  }
  function openLibraryMatch(work: LibraryWork, snapshot: string) {
    navigate(
      {
        view: "collection",
        lq: work.title,
        lp: 1,
        lo: "all",
        lx: "title",
        lg: "",
        lt: snapshot,
        lw: work.id,
        ls: "",
        ld: "1",
      },
      true,
    );
    window.scrollTo(0, 0);
  }
  useEffect(() => {
    const onPop = () => {
      const value = parameters();
      setRoute(value);
      setSearch(value.q);
      const saved = history.state?.librariumReturn;
      if (!value.work && saved)
        requestAnimationFrame(() => restoreList(saved.work, saved.scroll));
      if (value.work) selectionIntent.current = "list";
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setPollClock(Date.now()), 1500);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (search === route.q) return;
    const timer = setTimeout(() => navigate({ q: search, page: 1 }), 180);
    return () => clearTimeout(timer);
  }, [search, route.q, route.series, route.page, route.work, route.view]);
  useEffect(() => {
    if (route.work && detail.data && selectionIntent.current) {
      setSelectionAnnouncement(`${detail.data.title} selected.`);
      document.querySelector(".detail")?.scrollTo(0, 0);
      if (
        matchMedia("(max-width:959px), (max-height:679px)").matches ||
        selectionIntent.current === "history"
      )
        detailHeading.current?.focus({ preventScroll: true });
      selectionIntent.current = null;
    }
  }, [route.work, detail.data?.id]);
  useEffect(() => {
    const comparisonReturn = history.state?.catalogueComparisonReturn as
      CatalogueComparisonReturn | undefined;
    const returningComparison =
      comparisonReturn?.work === route.cw &&
      comparisonReturn?.version === route.cv &&
      comparisonReturn?.sha256 === route.ch &&
      Number.isFinite(comparisonReturn?.scroll) &&
      comparisonReturn.scroll >= 0 &&
      Number.isFinite(comparisonReturn.paneScroll) &&
      comparisonReturn.paneScroll >= 0;
    if (
      route.view !== "catalogue" ||
      !route.cw ||
      (!history.state?.reviewOrigin && !returningComparison)
    )
      return;
    let restored = false;
    let frame = 0;
    const intent = trackReturnIntent(() => cancelAnimationFrame(frame));
    const focusReviewedWork = () => {
      if (restored || !intent.isCurrent()) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!intent.isCurrent()) return;
        const heading =
          (returningComparison
            ? document.getElementById("catalogue-compare-source")
            : null) ??
          document.querySelector<HTMLHeadingElement>(".catalogue .work-title");
        if (heading) {
          restored = true;
          intent.dispose();
          if (
            returningComparison &&
            Array.isArray(comparisonReturn.disclosures) &&
            comparisonReturn.disclosures.length <= 256 &&
            comparisonReturn.disclosures.every(
              (open) => typeof open === "boolean",
            )
          ) {
            const disclosures =
              document.querySelectorAll<HTMLDetailsElement>(
                ".catalogue details",
              );
            if (disclosures.length === comparisonReturn.disclosures.length)
              disclosures.forEach((element, index) => {
                element.open = comparisonReturn.disclosures![index];
              });
          }
          heading.focus({ preventScroll: true });
          if (returningComparison) {
            document
              .querySelector<HTMLElement>(".catalogue .detail")
              ?.scrollTo(0, comparisonReturn.paneScroll);
            window.scrollTo(0, comparisonReturn.scroll);
          }
        }
      });
    };
    focusReviewedWork();
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (
        event.query.queryKey[0] === "catalogue-detail" &&
        event.query.state.status === "success"
      )
        focusReviewedWork();
    });
    return () => {
      intent.dispose();
      unsubscribe();
      cancelAnimationFrame(frame);
    };
  }, [route.view, route.cw, route.cv, route.ch, queryClient]);

  function merge(job: Job) {
    for (const query of queryClient
      .getQueryCache()
      .findAll({ queryKey: ["jobs"] })) {
      const key = query.queryKey;
      const kind =
        key.length === 2 && ["epub", "epub_validation"].includes(String(key[1]))
          ? key[1]
          : key[2] === "catalogue"
            ? "catalogue"
            : "";
      if (kind && kind !== job.kind) continue;
      queryClient.setQueryData<{ jobs: Job[] }>(key, (current) => ({
        jobs: mergeJobs(current?.jobs ?? [], [job]),
      }));
    }
    if (job.kind === "epub_validation" && job.source_job_id) {
      queryClient.setQueryData<Job>(
        ["epub-validation-job", job.source_job_id, job.id],
        (previous) =>
          !previous || job.revision >= previous.revision ? job : previous,
      );
      for (const query of queryClient.getQueryCache().findAll({
        queryKey: ["epub-validation-history", job.source_job_id],
      })) {
        queryClient.setQueryData<{ jobs: Job[] }>(query.queryKey, (current) =>
          current
            ? {
                ...current,
                jobs: current.jobs.map((previous) =>
                  previous.id === job.id && job.revision >= previous.revision
                    ? job
                    : previous,
                ),
              }
            : current,
        );
      }
    }
    if (job.kind === "book_assessment" || job.kind === "library_reconcile") {
      queryClient.setQueryData<Job>(["review-check", job.id], (previous) =>
        !previous || job.revision >= previous.revision ? job : previous,
      );
      void queryClient.invalidateQueries({ queryKey: ["review-history"] });
    }
  }
  function restoreCommandFocus(
    context: CommandFocus | undefined,
    jobId?: string,
  ) {
    const eligible = () =>
      context?.restoreFocus &&
      currentRoute.current.view === context.view &&
      currentRoute.current.work === context.work &&
      (!context.requestKey ||
        latestRequests.current.get(context.work) === context.requestKey) &&
      (document.activeElement === context.element ||
        document.activeElement === document.body);
    if (!eligible()) return;
    requestAnimationFrame(() => {
      if (!eligible()) return;
      const original = context?.element;
      const target =
        original instanceof HTMLButtonElement &&
        original.isConnected &&
        !original.disabled
          ? original
          : route.view === "inspections"
            ? document
                .getElementById(`inspection-${jobId}`)
                ?.querySelector<HTMLButtonElement>(".text-button")
            : document.querySelector<HTMLButtonElement>(
                ".actions button:not(:disabled)",
              );
      target?.focus({ preventScroll: true });
    });
  }
  const start = useMutation({
    onMutate: (work: string) => {
      const requestKey = intentKey(localStorage, work);
      latestRequests.current.set(work, requestKey);
      return {
        restoreFocus: document.activeElement?.classList.contains("primary"),
        element: document.activeElement,
        view: route.view,
        work,
        requestKey,
      };
    },
    mutationFn: async (workId: string) => {
      if (!session.data)
        throw new Error("Connection is not ready. Retry the connection first.");
      return api<Job>("jobs", {
        method: "POST",
        headers: {
          "X-CSRFToken": session.data.csrf,
          "Idempotency-Key": intentKey(localStorage, workId),
        },
        body: JSON.stringify({ work_id: workId }),
      });
    },
    onSuccess: (job, _variables, context) => {
      merge(job);
      const name = `librarium-intent:${job.work_id}`;
      if (localStorage.getItem(name) === job.request_key)
        localStorage.removeItem(name);
      if (
        currentRoute.current.view === context?.view &&
        currentRoute.current.work === context.work &&
        latestRequests.current.get(context.work) === context.requestKey
      )
        setNotice(commandNotice("inspect", job));
    },
    onError: (_error, _work, context) => {
      if (
        currentRoute.current.view === context?.view &&
        currentRoute.current.work === context.work &&
        latestRequests.current.get(context.work) === context.requestKey
      ) {
        const confirmed = queryClient
          .getQueriesData<{ jobs: Job[] }>({ queryKey: ["jobs"] })
          .flatMap(([, value]) => value?.jobs ?? [])
          .find((job) => job.request_key === context.requestKey);
        if (confirmed) {
          start.reset();
          setNotice(commandNotice("inspect", confirmed));
          return;
        }
        setNotice(
          "Inspection was not confirmed. Retry uses the same request key; refresh to check its state.",
        );
      }
    },
    onSettled: (_data, _error, _work, context) => restoreCommandFocus(context),
  });
  const stop = useMutation({
    onMutate: () => ({
      restoreFocus: document.activeElement?.classList.contains("cancel"),
      element: document.activeElement,
      view: route.view,
      work: route.work,
    }),
    mutationFn: async (job: Job) => {
      if (!session.data)
        throw new Error("Connection is not ready. Retry the connection first.");
      return api<Job>(`jobs/${job.id}`, {
        method: "POST",
        headers: { "X-CSRFToken": session.data.csrf },
        body: "{}",
      });
    },
    onSuccess: (job, _variables, context) => {
      merge(job);
      if (
        currentRoute.current.view === context?.view &&
        currentRoute.current.work === context.work
      )
        setNotice(commandNotice("cancel", job));
    },
    onError: (_error, _job, context) => {
      if (
        currentRoute.current.view === context?.view &&
        currentRoute.current.work === context.work
      )
        setNotice(
          "Cancellation was not confirmed. Refresh progress or retry cancellation.",
        );
    },
    onSettled: (_data, _error, job, context) =>
      restoreCommandFocus(context, job.id),
  });
  useEffect(() => {
    start.reset();
    stop.reset();
    setNotice("");
  }, [route.work, route.view]);
  const jobList = [...(jobs.data?.jobs ?? [])].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  useEffect(() => {
    if (jobs.data) {
      for (const job of jobs.data.jobs) {
        const name = `librarium-intent:${job.work_id}`;
        if (job.request_key && localStorage.getItem(name) === job.request_key) {
          localStorage.removeItem(name);
          if (start.isError && start.variables === job.work_id) {
            start.reset();
            if (currentRoute.current.work === job.work_id)
              setNotice(commandNotice("inspect", job));
          }
        }
      }
      announceTerminal(jobs.data.jobs);
    }
  }, [jobs.data, announceTerminal]);
  useEffect(() => {
    if (fileJobs.data) announceTerminal(fileJobs.data.jobs);
  }, [fileJobs.data, announceTerminal]);
  useEffect(() => {
    if (validationJobs.data) announceTerminal(validationJobs.data.jobs);
  }, [validationJobs.data, announceTerminal]);
  const fileJobList = fileJobs.data?.jobs ?? [];
  const validationJobList = validationJobs.data?.jobs ?? [];
  const selectedJob = jobList.find((job) => job.work_id === route.work);
  const running = mergeJobs(
    mergeJobs(jobList, fileJobList),
    validationJobList,
  ).filter(live).length;
  const pendingStart = start.isPending && start.variables === route.work;
  const pendingStop = stop.isPending && stop.variables?.id === selectedJob?.id;
  const issue = start.error?.message || stop.error?.message;
  const observingJobs =
    route.view === "inspections" ||
    (route.view === "collection" && !realLibrary);
  const observingFiles = route.view === "files";
  const readError =
    (observingJobs && jobs.error) ||
    (observingFiles && fileJobs.error) ||
    session.error;
  const stalePoll =
    (observingJobs &&
      !!jobs.dataUpdatedAt &&
      pollClock - jobs.dataUpdatedAt > 6000) ||
    (observingFiles &&
      !!fileJobs.dataUpdatedAt &&
      pollClock - fileJobs.dataUpdatedAt > 6000);
  const connectionInterrupted = readError && !(readError instanceof ApiError);

  async function refresh() {
    setRefreshing(true);
    try {
      const [jobsResult, sessionResult, fileResult] = await Promise.all([
        observingFiles ? fileJobs.refetch() : jobs.refetch(),
        session.refetch(),
        observingFiles ? jobs.refetch() : fileJobs.refetch(),
        queryClient.refetchQueries({
          queryKey: ["review-history"],
          type: "active",
        }),
        queryClient.refetchQueries({ queryKey: ["file-job"], type: "active" }),
        queryClient.refetchQueries({
          queryKey: ["review-check"],
          type: "active",
        }),
      ]);
      const historyFailed = queryClient
        .getQueryCache()
        .findAll({ type: "active" })
        .filter((query) =>
          ["review-history", "review-check"].includes(
            String(query.queryKey[0]),
          ),
        )
        .some((query) => query.state.status === "error");
      setNotice(
        jobsResult.isError ||
          sessionResult.isError ||
          (observingFiles && fileResult.isError) ||
          historyFailed
          ? "The last progress refresh was incomplete. Use Refresh progress to try again."
          : "Progress refreshed.",
      );
    } finally {
      setRefreshing(false);
    }
  }
  function openWork(id: string) {
    document.querySelector(".detail")?.scrollTo(0, 0);
    selectionIntent.current = route.view === "inspections" ? "history" : "list";
    focusReturn.current = id;
    scrollReturn.current = window.scrollY;
    const fromList = route.view === "collection" && !route.work;
    if (fromList)
      history.replaceState(
        { librariumReturn: { work: id, scroll: window.scrollY } },
        "",
      );
    navigate(
      { work: id, view: "collection" },
      true,
      fromList ? { librariumDetailFromList: true } : null,
    );
    if (
      matchMedia("(max-width: 959px), (max-height:679px)").matches ||
      route.view === "inspections"
    )
      window.scrollTo(0, 0);
  }
  const openingWorkspace = "Opening preserved book workspace…";
  const resumeRequest = useRef<{
    controller: AbortController;
    route: typeof route;
  } | null>(null);
  function cancelResume() {
    if (!resumeRequest.current) return;
    resumeRequest.current.controller.abort();
    resumeRequest.current = null;
    setNotice((current) => (current === openingWorkspace ? "" : current));
  }
  useEffect(() => {
    if (resumeRequest.current && resumeRequest.current.route !== route)
      cancelResume();
  }, [route]);
  useEffect(
    () => () => {
      resumeRequest.current?.controller.abort();
      resumeRequest.current = null;
    },
    [],
  );
  async function openReviewedWork(job: Job) {
    cancelResume();
    if (isRetiredKind(job.kind)) return;
    const boundAssessment =
      job.kind === "book_assessment" &&
      job.source_job_id &&
      /^[a-f0-9]{64}$/.test(job.source_sha256 ?? "") &&
      /^[a-f0-9]{64}$/.test(job.source_report_sha256 ?? "") &&
      job.catalogue_version &&
      /^[a-f0-9]{64}$/.test(job.catalogue_sha256 ?? "") &&
      job.catalogue_work_id &&
      job.reconciliation_key;
    if (job.kind === "epub_validation" && !job.source_job_id) {
      setNotice(
        "This EPUBCheck does not record a source inspection to reopen.",
      );
      return;
    }
    if (
      job.kind === "library_reconcile" ||
      (job.kind === "book_assessment" && !boundAssessment)
    ) {
      navigate({ rj: job.id }, true);
      return;
    }
    if (
      ["epub", "epub_validation", "book_assessment"].includes(job.kind ?? "")
    ) {
      const controller = new AbortController();
      const sourceRoute = currentRoute.current;
      resumeRequest.current = { controller, route: sourceRoute };
      const origin: ReviewReturn = {
        route: { rq: sourceRoute.rq, rs: sourceRoute.rs, rp: sourceRoute.rp },
        jobId: job.id,
        scroll: window.scrollY,
      };
      setNotice(openingWorkspace);
      try {
        const pins = await resolveWorkspace(job.id, controller.signal);
        if (controller.signal.aborted || currentRoute.current !== sourceRoute)
          return;
        history.replaceState({ ...history.state, reviewReturn: origin }, "");
        navigate(
          { view: "files", ...pins, fcw: "", fcv: "", fch: "", rj: "" },
          true,
          { reviewOrigin: origin },
        );
        window.scrollTo(0, 0);
        setNotice((current) =>
          current === openingWorkspace
            ? "Preserved book workspace opened."
            : current,
        );
      } catch (error) {
        if (!controller.signal.aborted && currentRoute.current === sourceRoute)
          setNotice((current) =>
            current === openingWorkspace
              ? error instanceof Error
                ? error.message
                : "Saved workspace could not open. Retry this record."
              : current,
          );
      } finally {
        if (resumeRequest.current?.controller === controller) {
          resumeRequest.current = null;
          if (controller.signal.aborted || currentRoute.current !== sourceRoute)
            setNotice((current) =>
              current === openingWorkspace ? "" : current,
            );
        }
      }
      return;
    }
    const origin: ReviewReturn = {
      route: { rq: route.rq, rs: route.rs, rp: route.rp },
      jobId: job.id,
      scroll: window.scrollY,
    };
    history.replaceState({ ...history.state, reviewReturn: origin }, "");
    if (job.kind === "catalogue") {
      navigate(
        {
          view: "catalogue",
          cw: job.work_id,
          cv: job.source_version,
          ch: job.source_sha256 ?? "",
          cs: "",
          ca: "",
          cb: "works",
          cq: "",
          cp: 1,
        },
        true,
        { reviewOrigin: origin },
      );
      window.scrollTo(0, 0);
    } else {
      openWork(job.work_id);
      history.replaceState({ ...history.state, reviewOrigin: origin }, "");
    }
  }
  function returnToReviews() {
    const origin: ReviewReturn | undefined = history.state?.reviewOrigin;
    if (!origin) return;
    navigate(
      {
        view: "inspections",
        work: "",
        fj: "",
        fv: "",
        fa: "",
        rj: "",
        ...origin.route,
      },
      true,
      {
        reviewReturn: origin,
      },
    );
  }
  function returnToFiles() {
    const origin: FileReturn | undefined = history.state?.fileOrigin;
    if (!origin) return;
    navigate(
      {
        fj: "",
        fv: "",
        fa: "",
        fq: origin.route.rq,
        fs: origin.route.rs,
        fp: origin.route.rp,
      },
      true,
      { fileReturn: origin },
    );
  }
  function closeWork() {
    if (history.state?.reviewOrigin) {
      returnToReviews();
      return;
    }
    if (history.state?.librariumDetailFromList) {
      history.back();
      return;
    }
    const selected = focusReturn.current || route.work;
    navigate({ work: "" });
    requestAnimationFrame(() => restoreList(selected, scrollReturn.current));
  }
  function restoreList(selected: string, scroll: number) {
    const target =
      document.getElementById(`work-${selected}`) ??
      document.querySelector<HTMLInputElement>(".search input");
    target?.focus({ preventScroll: true });
    window.scrollTo(0, scroll);
  }
  const emptyInstallation =
    collection.data?.total === 0 &&
    !collection.isPlaceholderData &&
    !collection.isError &&
    !route.q &&
    !route.series &&
    route.page === 1;

  const workspaceNavigation = (
    <nav key="navigation" aria-label="Workspace" className="navigation">
      {session.data?.direct_library && (
        <button
          aria-current={route.view === "home" ? "page" : undefined}
          onClick={() => navigate({ view: "home" }, true)}
        >
          Home
        </button>
      )}
      <button
        aria-current={route.view === "collection" ? "page" : undefined}
        onClick={() =>
          realLibrary && history.state?.libraryOrigin
            ? returnToLibrary()
            : navigate({ view: "collection" }, true)
        }
      >
        {realLibrary ? "Library" : "Collection"}
      </button>
      <button
        aria-current={
          route.view === "catalogue" && route.cb === "series"
            ? "page"
            : undefined
        }
        onClick={() =>
          navigate({ view: "catalogue", cm: "browse", cb: "series" }, true)
        }
      >
        Series
      </button>
      <button
        aria-current={
          route.view === "catalogue" && route.cb !== "series"
            ? "page"
            : undefined
        }
        onClick={() =>
          navigate({ view: "catalogue", cm: "health", cb: "works" }, true)
        }
      >
        Catalogue
      </button>
      <button
        aria-current={
          ["inspections", "files", "covers"].includes(route.view)
            ? "page"
            : undefined
        }
        onClick={() =>
          navigate({ view: nativeLibrary ? "covers" : "inspections" }, true)
        }
      >
        {realLibrary ? "Reviews" : "Inspections"}{" "}
        {running > 0 && <span className="count">{running} active</span>}
      </button>
    </nav>
  );
  function openCatalogueOperations() {
    navigate({ cm: "operations", cw: "", cs: "", ca: "", cq: "" }, true);
  }
  const catalogueSection =
    route.cm === "health"
      ? "health"
      : nativeLibrary &&
          route.cm === "operations" &&
          !route.cw &&
          !route.cs &&
          !route.ca &&
          !route.cq
        ? "operations"
        : "browse";
  const catalogueTabs = (
    <nav className="catalogue-tabs" aria-label="Catalogue sections">
      <button
        aria-current={catalogueSection === "health" ? "page" : undefined}
        onClick={() => navigate({ cm: "health" }, true)}
      >
        Tool health
      </button>
      <button
        aria-current={catalogueSection === "browse" ? "page" : undefined}
        onClick={() => navigate({ cm: "browse" }, true)}
      >
        Books
      </button>
      {nativeLibrary && (
        <button
          aria-current={catalogueSection === "operations" ? "page" : undefined}
          onClick={openCatalogueOperations}
        >
          Catalogue operations
        </button>
      )}
    </nav>
  );
  const workspaceSearchSlot =
    (realLibrary && route.view === "collection") ||
    route.view === "catalogue" ? (
      <div key="workspace-search" id="workspace-search-slot" />
    ) : null;
  const themePicker = session.data?.direct_library ? (
    <button
      key="settings"
      type="button"
      className="gear"
      aria-label="Settings"
      aria-current={route.view === "settings" ? "page" : undefined}
      onClick={() => navigate({ view: "settings" }, true)}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm8.3 4.9-1.9.4a6.9 6.9 0 0 1-.7 1.6l1.1 1.6-1.7 1.7-1.6-1.1c-.5.3-1 .5-1.6.7l-.4 1.9h-2.4l-.4-1.9a6.9 6.9 0 0 1-1.6-.7l-1.6 1.1-1.7-1.7 1.1-1.6a6.9 6.9 0 0 1-.7-1.6l-1.9-.4v-2.4l1.9-.4c.2-.6.4-1.1.7-1.6L5.3 6.4 7 4.7l1.6 1.1c.5-.3 1-.5 1.6-.7l.4-1.9H13l.4 1.9c.6.2 1.1.4 1.6.7L16.6 4.7l1.7 1.7-1.1 1.6c.3.5.5 1 .7 1.6l1.9.4v2.4Z" />
      </svg>
    </button>
  ) : (
    <ThemePicker key="theme-picker" />
  );

  return (
    <>
      <a className="skip" href="#main">
        Skip to workspace
      </a>
      <header
        className={`masthead ${route.view === "covers" ? "cover-review-masthead" : ""}`}
      >
        <div className="brand">
          <ArchivistMark variant="small" />
          <LibrariumWordmark />
        </div>
        {(connectionInterrupted || readError || stalePoll) && (
          <span className="connection">
            {connectionInterrupted
              ? "Offline"
              : readError
                ? "Request failed"
                : "Refresh progress"}
          </span>
        )}
        {desktopMasthead
          ? [workspaceNavigation, workspaceSearchSlot, themePicker]
          : [themePicker, workspaceNavigation, workspaceSearchSlot]}
      </header>
      <div className="shell">
        <main id="main">
          {!realLibrary &&
          route.view !== "files" &&
          (collection.data?.total ||
            jobList.some(
              (job) =>
                !job.kind ||
                job.kind === "synthetic" ||
                job.result.synthetic === true,
            )) ? (
            <p className="context-note">Demo data</p>
          ) : null}
          {(readError || stalePoll) && (
            <div
              className={readError ? "error" : "context-note"}
              role={readError ? "alert" : "status"}
            >
              {connectionInterrupted
                ? "Unable to reach the local service. Showing saved content where available."
                : readError
                  ? `Request could not complete: ${readError.message}.`
                  : "Saved progress may be out of date. Refresh to check."}{" "}
              <button onClick={refresh}>
                {readError ? "Retry request" : "Refresh saved progress"}
              </button>
            </div>
          )}
          {nativeLibrary && ["covers", "inspections"].includes(route.view) && (
            <nav className="catalogue-tabs" aria-label="Review sections">
              <button
                aria-current={route.view === "covers" ? "page" : undefined}
                onClick={() => navigate({ view: "covers" }, true)}
              >
                Covers
              </button>
              <button
                aria-current={route.view === "inspections" ? "page" : undefined}
                onClick={() => navigate({ view: "inspections" }, true)}
              >
                History
              </button>
            </nav>
          )}
          {route.view === "covers" ? (
            <CoverReview
              session={session.data}
              route={route}
              navigate={navigate}
            />
          ) : route.view === "catalogue" && route.cm === "health" ? (
            <>
              {catalogueTabs}
              <CatalogueHealth
                openWork={(id, pin) =>
                  navigate(
                    {
                      cm: "browse",
                      cb: "works",
                      cw: id,
                      cv: pin.version,
                      ch: pin.sha256,
                      cs: "",
                      ca: "",
                      cq: "",
                      cp: 1,
                    },
                    true,
                  )
                }
                openOperations={
                  nativeLibrary ? () => openCatalogueOperations() : undefined
                }
              />
            </>
          ) : route.view === "catalogue" &&
            nativeLibrary &&
            route.cm === "operations" &&
            !route.cw &&
            !route.cs &&
            !route.ca &&
            !route.cq ? (
            <>
              {catalogueTabs}
              <CatalogueControl route={route} navigate={navigate} />
            </>
          ) : route.view === "catalogue" ? (
            <>
              {catalogueTabs}
              {history.state?.reviewOrigin && (
                <button className="review-return" onClick={returnToReviews}>
                  Return to reviews
                </button>
              )}
              {history.state?.bookWorkspaceOrigin && (
                <button
                  className="context-return"
                  onClick={returnToBookWorkspace}
                >
                  Return to book workspace
                </button>
              )}
              {history.state?.nativeLibraryOrigin && (
                <button
                  className="context-return"
                  onClick={returnToNativeLibrary}
                >
                  Return to library book
                </button>
              )}
              <Catalogue
                route={route}
                navigate={navigate}
                libraryConnected={realLibrary && !nativeLibrary}
                reviewsEnabled={!!session.data}
                compareSource={
                  fileInspections ? compareCatalogueSource : undefined
                }
                openLibrary={openLibraryMatch}
                returnToLibrary={
                  history.state?.libraryOrigin ? returnToLibrary : undefined
                }
              />
            </>
          ) : route.view === "settings" && session.data?.direct_library ? (
            <Settings />
          ) : route.view === "home" && session.data?.direct_library ? (
            <Home
              openBook={(id, token) =>
                navigate(
                  { view: "collection", lw: id, lt: token, ld: "1" },
                  true,
                )
              }
              openLibrary={() => navigate({ view: "collection" }, true)}
            />
          ) : route.view === "collection" && session.data?.direct_library ? (
            <DirectLibrary
              route={route}
              navigate={navigate}
              inspectBook={fileInspections ? inspectLibraryBook : undefined}
              resumeBook={openNativeWorkspace}
              restore={history.state?.nativeLibraryReturn}
              openReference={(workId, pin) => {
                const origin = { ...nativeOrigin(), reference: pin };
                history.replaceState(
                  { ...history.state, nativeLibraryReturn: origin },
                  "",
                );
                navigate(
                  {
                    view: "catalogue",
                    cm: "browse",
                    cw: workId,
                    cb: "works",
                    cv: pin.version,
                    ch: pin.sha256,
                    cs: "",
                    ca: "",
                    cq: "",
                    cp: 1,
                  },
                  true,
                  {
                    nativeLibraryOrigin: origin,
                  },
                );
              }}
            />
          ) : route.view === "collection" && realLibrary ? (
            <Library
              route={route}
              navigate={navigate}
              openCatalogue={openCatalogue}
            />
          ) : (
            <>
              {route.work && route.view === "collection" && (
                <button className="back" onClick={closeWork}>
                  {history.state?.reviewOrigin
                    ? "Return to reviews"
                    : "Back to collection"}
                </button>
              )}
              <div
                className={`page-heading ${route.work && route.view === "collection" ? "is-detail" : ""}`}
              >
                <div>
                  {!(route.view === "files" && route.fj) && (
                    <h1>
                      {route.view === "collection"
                        ? "Your collection"
                        : route.view === "files"
                          ? route.fj
                            ? "Book workspace"
                            : "Incoming books"
                          : realLibrary
                            ? "Reviews and history"
                            : "Inspection history"}
                    </h1>
                  )}
                </div>
                <div className="page-actions">
                  {route.view === "inspections" && fileInspections && (
                    <button
                      className="secondary"
                      onClick={() => {
                        navigate({ view: "files", fj: "" }, true);
                        window.scrollTo(0, 0);
                      }}
                    >
                      Inspect an EPUB
                    </button>
                  )}
                  <button
                    className="secondary"
                    onClick={refresh}
                    disabled={refreshing}
                  >
                    {refreshing ? "Refreshing…" : "Refresh progress"}
                  </button>
                </div>
              </div>
              <p className="announcement" role="status" aria-live="polite">
                {notice}
              </p>
              <p className="sr-only" role="status" aria-live="polite">
                {selectionAnnouncement}
              </p>
              <p
                className="announcement job-announcement"
                role="status"
                aria-live="polite"
              >
                {jobAnnouncement}
              </p>
              {issue && (
                <p className="error" role="alert">
                  {issue}
                </p>
              )}
              {route.view === "collection" ? (
                <div
                  className={`collection-layout ${route.work ? "has-selection" : ""} ${emptyInstallation ? "first-collection" : ""}`}
                >
                  <section
                    className="collection"
                    aria-label="Collection results"
                    aria-busy={collection.isFetching}
                  >
                    {!emptyInstallation && (
                      <div className="filters">
                        <label className="search">
                          Search collection
                          <input
                            type="search"
                            value={search}
                            maxLength={200}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Title, author or series"
                          />
                        </label>
                        <label>
                          Series
                          <select
                            value={route.series}
                            onChange={(event) =>
                              navigate({ series: event.target.value, page: 1 })
                            }
                          >
                            <option value="">All series</option>
                            {[
                              "The Meridian Papers",
                              "The Northern Archive",
                              "Tideland Stories",
                            ].map((value) => (
                              <option key={value}>{value}</option>
                            ))}
                          </select>
                        </label>
                      </div>
                    )}
                    {!emptyInstallation && (
                      <div className="list-summary" role="status">
                        {collection.isPlaceholderData
                          ? "Updating results… Previous results remain visible."
                          : collection.isPending
                            ? "Loading collection…"
                            : collection.isError
                              ? "Collection unavailable"
                              : `${collection.data?.total.toLocaleString()} works`}
                      </div>
                    )}
                    {collection.isError && (
                      <div className="empty">
                        <h2>Collection could not load</h2>
                        <p>{collection.error.message}</p>
                        <button onClick={() => collection.refetch()}>
                          Retry collection
                        </button>
                      </div>
                    )}
                    {collection.isPending && (
                      <div className="loading" aria-label="Loading collection">
                        <div />
                        <div />
                        <div />
                      </div>
                    )}
                    {collection.data?.total === 0 &&
                      (route.q || route.series || route.page > 1 ? (
                        <div className="empty">
                          <h2>No works match this search</h2>
                          <p>
                            Try part of a title, an author, or another series.
                          </p>
                          <button
                            onClick={() => {
                              setSearch("");
                              navigate({ q: "", series: "", page: 1 });
                            }}
                          >
                            Clear filters
                          </button>
                        </div>
                      ) : (
                        <div className="empty first-run">
                          <ArchivistMark variant="small" />
                          <h2>Your library starts here</h2>
                          <p>
                            No collection is connected yet. Start with the
                            catalogue to browse works, editions and their
                            sources.
                          </p>
                          <button
                            className="primary"
                            onClick={() => navigate({ view: "catalogue" })}
                          >
                            Open catalogue
                          </button>
                        </div>
                      ))}
                    <ul className="work-list">
                      {collection.data?.works.map((work) => (
                        <li key={work.id}>
                          <button
                            id={`work-${work.id}`}
                            className="work-row"
                            aria-pressed={route.work === work.id}
                            onClick={() => openWork(work.id)}
                          >
                            <span className="bibliography">
                              <strong>{work.title}</strong>
                              <span className="work-meta">
                                <span>{work.author}</span>
                                <span className="series-name">
                                  {work.series}
                                </span>
                              </span>
                            </span>
                            <span className="edition-count">
                              {work.edition_count}{" "}
                              {work.edition_count === 1
                                ? "edition"
                                : "editions"}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    {!!collection.data?.total && (
                      <div className="pagination">
                        <button
                          onClick={() => navigate({ page: route.page - 1 })}
                          disabled={route.page === 1}
                        >
                          Previous
                        </button>
                        <span>
                          Page {route.page} of{" "}
                          {Math.ceil(collection.data.total / 24)}
                        </span>
                        <button
                          onClick={() => navigate({ page: route.page + 1 })}
                          disabled={route.page * 24 >= collection.data.total}
                        >
                          Next
                        </button>
                      </div>
                    )}
                  </section>
                  <aside
                    className={`detail ${emptyInstallation ? "no-collection" : ""}`}
                    aria-label="Selected work"
                  >
                    {route.work ? (
                      <>
                        {detail.isPending ? (
                          <p role="status">Loading work and evidence…</p>
                        ) : detail.isError ? (
                          <div className="error" role="alert">
                            Unable to load this work.{" "}
                            <button onClick={() => detail.refetch()}>
                              Retry work
                            </button>
                          </div>
                        ) : (
                          detail.data && (
                            <div className="folio" key={detail.data.id}>
                              <h2
                                ref={detailHeading}
                                tabIndex={-1}
                                className="work-title"
                              >
                                {detail.data.title}
                              </h2>
                              <p className="author">{detail.data.author}</p>
                              <p className="series-detail">
                                {detail.data.series}
                              </p>
                              <section className="inspection detail-section">
                                <h3>Metadata inspection</h3>
                                <p>
                                  Compare the saved title and validate its ISBN.
                                  Your library stays unchanged.
                                </p>
                                {detail.data.fault && (
                                  <p className="context-note">
                                    This fixture intentionally fails its first
                                    inspection so you can try recovery.
                                  </p>
                                )}
                                <div className="actions">
                                  <button
                                    className="primary"
                                    disabled={
                                      pendingStart ||
                                      !!(selectedJob && live(selectedJob)) ||
                                      !session.data ||
                                      !jobs.data
                                    }
                                    onClick={() => {
                                      setNotice("Requesting inspection…");
                                      start.mutate(detail.data!.id);
                                    }}
                                  >
                                    {pendingStart
                                      ? "Requesting inspection…"
                                      : selectedJob?.state === "failed"
                                        ? "Retry inspection"
                                        : selectedJob?.state === "succeeded"
                                          ? "Inspect again"
                                          : "Inspect metadata"}
                                  </button>
                                  {selectedJob && live(selectedJob) && (
                                    <button
                                      className="cancel"
                                      disabled={pendingStop}
                                      onClick={() => {
                                        setNotice("Requesting cancellation…");
                                        stop.mutate(selectedJob);
                                      }}
                                    >
                                      {pendingStop
                                        ? "Cancelling…"
                                        : "Cancel inspection"}
                                    </button>
                                  )}
                                </div>
                                {selectedJob && (
                                  <JobProgress job={selectedJob} />
                                )}
                              </section>
                              <section className="detail-section">
                                <h3>
                                  Editions{" "}
                                  <span>{detail.data.editions.length}</span>
                                </h3>
                                <ul className="editions">
                                  {detail.data.editions.map((edition) => (
                                    <li key={edition.id}>
                                      <strong>{edition.format}</strong>
                                      <span>{edition.year}</span>
                                      <small>
                                        {edition.isbn
                                          ? `ISBN ${edition.isbn}`
                                          : "No ISBN supplied"}
                                      </small>
                                    </li>
                                  ))}
                                </ul>
                              </section>
                              <section className="detail-section">
                                <h3>Compare the evidence</h3>
                                <div className="comparison">
                                  <div>
                                    <h4>Catalogue title</h4>
                                    <p>{detail.data.title}</p>
                                  </div>
                                  <div>
                                    <h4>Library title</h4>
                                    <p>{detail.data.library_title}</p>
                                  </div>
                                  <div>
                                    <h4>Catalogue ISBN</h4>
                                    <p>
                                      {detail.data.editions[0]?.isbn ??
                                        "No ISBN supplied"}
                                    </p>
                                  </div>
                                  <div>
                                    <h4>Library ISBN</h4>
                                    <p>{detail.data.library_isbn}</p>
                                    <p className="context-note">
                                      {selectedJob?.result.findings?.find(
                                        (finding) =>
                                          finding.name === "ISBN checksum",
                                      )?.detail ?? "Checksum not yet checked."}
                                    </p>
                                  </div>
                                </div>
                                <p className="context-note">
                                  Titles are separate claims. An ISBN checksum
                                  cannot establish work identity.
                                </p>
                                <details>
                                  <summary>Source and binding</summary>
                                  <dl className="provenance">
                                    <dt>Source version</dt>
                                    <dd>{detail.data.source_version}</dd>
                                    <dt>Library UUID</dt>
                                    <dd>{detail.data.library_uuid}</dd>
                                    <dt>Edition</dt>
                                    <dd>
                                      {detail.data.editions[0]?.id ??
                                        "No edition supplied"}
                                    </dd>
                                    <dt>Work</dt>
                                    <dd>{detail.data.id}</dd>
                                    <dt>Evidence</dt>
                                    <dd>
                                      {detail.data.evidence[0].source} /{" "}
                                      {detail.data.evidence[0].native_id}
                                    </dd>
                                    <dt>Observed</dt>
                                    <dd>
                                      {detail.data.evidence[0].observed_at}
                                    </dd>
                                    <dt>File fingerprint</dt>
                                    <dd className="hash">
                                      {detail.data.file_sha256}
                                    </dd>
                                  </dl>
                                </details>
                              </section>
                            </div>
                          )
                        )}
                      </>
                    ) : (
                      <div className="detail-empty">
                        <ArchivistMark />
                        <h2>A closer look</h2>
                        <p>
                          Select a work to see its editions, compare its
                          evidence and inspect its metadata.
                        </p>
                      </div>
                    )}
                  </aside>
                </div>
              ) : route.view === "files" ? (
                <FileInspections
                  route={route}
                  navigate={navigate}
                  returnToLibrary={
                    history.state?.nativeLibraryOrigin
                      ? returnToNativeLibrary
                      : undefined
                  }
                  browseReferences={browseBookReferences}
                  restoreWorkspace={history.state?.bookWorkspaceReturn}
                  libraryContext={history.state?.nativeLibraryOrigin}
                  returnToCatalogue={
                    route.cw && route.cv && route.ch
                      ? returnToCatalogueWork
                      : undefined
                  }
                  session={session.data}
                  sessionPending={session.isPending}
                  sessionError={session.error}
                  retrySession={() => void session.refetch()}
                  jobs={fileJobList}
                  merge={merge}
                  cancel={(job) => stop.mutate(job)}
                  cancelling={stop.isPending ? stop.variables?.id : undefined}
                  announceTerminal={announceTerminal}
                  restore={history.state?.fileReturn}
                  back={history.state?.fileOrigin ? returnToFiles : undefined}
                  returnToReviews={() =>
                    history.state?.reviewOrigin
                      ? returnToReviews()
                      : navigate({ view: "inspections", fj: "", fv: "" }, true)
                  }
                  notify={setNotice}
                />
              ) : (
                <ReviewHistory
                  route={route}
                  navigate={navigate}
                  realLibrary={realLibrary}
                  kind={
                    route.rk
                      ? route.rk === "all"
                        ? ""
                        : (route.rk as HistoryKind)
                      : undefined
                  }
                  selectKind={(kind) =>
                    navigate({ rk: kind || "all", rp: 1, rj: "" }, true)
                  }
                  selectedId={route.rj}
                  closeSelected={() => navigate({ rj: "" }, true)}
                  enabled={!!session.data}
                  latestJobs={jobs.data?.jobs ?? []}
                  open={openReviewedWork}
                  cancel={(job) => stop.mutate(job)}
                  cancelling={stop.isPending ? stop.variables?.id : undefined}
                  restore={history.state?.reviewReturn}
                  browse={() =>
                    navigate({ view: realLibrary ? "catalogue" : "collection" })
                  }
                  chooseSource={
                    fileInspections
                      ? () => {
                          navigate(
                            {
                              view: "files",
                              fj: "",
                              ...clearWorkspace,
                              fcw: "",
                              fcv: "",
                              fch: "",
                            },
                            true,
                          );
                          window.scrollTo(0, 0);
                        }
                      : undefined
                  }
                  announceTerminal={announceTerminal}
                />
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
}
