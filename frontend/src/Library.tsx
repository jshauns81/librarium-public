import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { BrowseView, useBrowseView } from "./BrowseView";
import { type Cover } from "./BookCover";
import { LibraryBookDetails } from "./LibraryBookDetails";
import { LibraryBookArt } from "./LibraryBookArt";
import { LibraryBookPane } from "./LibraryBookPane";
import "./reading-room.css";
import { SeriesName } from "./SeriesName";

export type LibraryRoute = {
  lq: string;
  lp: number;
  lo: string;
  lx: string;
  lt: string;
  lw?: string;
  ls?: string;
  ld?: string;
  lg?: string;
};
export type LibraryReturn = {
  route: LibraryRoute;
  work: string;
  scroll: number;
  open: string[];
  shelf?: string;
  shelfScroll?: Record<string, number>;
  focusId?: string;
  catalogue?: { version: string; sha256: string };
};
export type CatalogueSelection = {
  cw?: string;
  cs?: string;
  cv: string;
  ch: string;
};
type Copy = { calibre_id: number; title: string; last_known: boolean };
export type LibraryWork = {
  id: string;
  title: string;
  kind: string;
  authors: string[];
  series: {
    id: string;
    name: string;
    position: number | null;
    lead_work_id?: string;
    position_total?: number;
    work_count?: number;
    shelf_eligible?: boolean;
  }[];
  shelf_alternates?: number;
  first_published?: string | null;
  state: "direct" | "contained" | "pending" | "missing" | "unknown";
  current: boolean;
  copies: Copy[];
  contained_in: Copy[];
  candidates: { title: string; stage: string; confidence: string }[];
};
export type Shelf = {
  id: string | null;
  name: string;
  total: number;
  catalogue_total: number | null;
  works: LibraryWork[];
  authors?: string[];
  credit?: { names: string[]; others: number };
  kinds?: Record<string, number>;
  truncated?: boolean;
  prefix_complete?: boolean;
  inspected?: number;
  total_is_lower_bound?: boolean;
  counts_complete?: boolean;
  counts: Record<string, number>;
  position_counts: { numbered: number; zero: number; unpositioned: number };
};
export type LibraryListing = {
  status: "ready" | "loading" | "preparing" | "version_mismatch";
  source: "library_finish";
  catalogue_version: string | null;
  checked_at: string | null;
  coverage: "complete" | "partial" | "unknown";
  loading: boolean;
  snapshot: string;
  page: number;
  page_size: number;
  total: number;
  works: LibraryWork[];
  shelves?: Shelf[];
  series_total?: number;
  series_scope?: "matching" | "catalogue";
  truncated?: boolean;
  unlinked_total?: number;
  finish_origin?: string;
  catalogue_snapshot?: { version: string; sha256: string; fixture: boolean };
};
export type CataloguePin = {
  status: string;
  version?: string;
  sha256?: string;
  fixture?: boolean;
};
const orderKey = "librarium.library-order";
const expiredChecks = new WeakMap<QueryClient, Set<string>>();
export function defaultLibraryOrder() {
  try {
    const saved = localStorage.getItem(orderKey);
    return saved === "title" || saved === "author" ? saved : "series";
  } catch {
    return "series";
  }
}
export const checkLabel = (coverage: LibraryListing["coverage"]) =>
  coverage === "complete"
    ? "Complete check"
    : coverage === "partial"
      ? "Partial check"
      : "Coverage unknown";
export const matchLabels = {
  direct: "Direct match",
  contained: "In a collection",
  pending: "Pending ID",
  missing: "No matched copy",
  unknown: "Unconfirmed",
};
export const savedMatch = (work: LibraryWork) =>
  !work.current && ["direct", "contained"].includes(work.state);
function historicalListing(data: LibraryListing): LibraryListing {
  const historicalWork = (work: LibraryWork): LibraryWork => ({
    ...work,
    current: false,
    state: work.state === "missing" ? "unknown" : work.state,
    copies: work.copies.map((copy) => ({ ...copy, last_known: true })),
    contained_in: work.contained_in.map((copy) => ({
      ...copy,
      last_known: true,
    })),
  });
  return {
    ...data,
    coverage: "unknown",
    works: data.works.map(historicalWork),
    shelves: data.shelves?.map((shelf) => ({
      ...shelf,
      works: shelf.works.map(historicalWork),
      counts: {
        ...shelf.counts,
        saved:
          (shelf.counts.saved ?? 0) +
          (shelf.counts.direct ?? 0) +
          (shelf.counts.contained ?? 0),
        direct: 0,
        contained: 0,
        missing: 0,
        unknown: (shelf.counts.unknown ?? 0) + (shelf.counts.missing ?? 0),
      },
    })),
  };
}
export function shelfCredits(authors: string[]) {
  const names = [...new Set(authors)];
  const others = names.length - 2;
  return others > 0
    ? `${names.slice(0, 2).join(", ")} and ${others} ${others === 1 ? "other" : "others"}`
    : names.join(", ") || "Author not recorded";
}
export const dateLabel = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "No check date";
const key = (r: LibraryRoute, generation: number, pin?: CataloguePin) => [
  "library",
  r.lq,
  r.lp,
  r.lo,
  r.lx,
  r.lt,
  r.lg ?? "",
  generation,
  pin?.version,
  pin?.sha256,
];

export function preferredMembership(
  work: LibraryWork,
  seriesId?: string | null,
) {
  const eligible = work.series.filter(
    (series) => series.shelf_eligible !== false,
  );
  return (
    work.series.find((s) => s.id === seriesId) ??
    (eligible.length ? eligible : work.series).reduce<
      LibraryWork["series"][number] | undefined
    >(
      (best, member) =>
        !best || (member.work_count ?? 0) > (best.work_count ?? 0)
          ? member
          : best,
      undefined,
    )
  );
}

export function positionLabel(work: LibraryWork, seriesId?: string | null) {
  const member = preferredMembership(work, seriesId);
  const position = member?.position;
  if (position == null) return "No position";
  return position === 0 ||
    (member?.lead_work_id && member.lead_work_id !== work.id)
    ? `Position ${position}`
    : `Book ${position}`;
}

function ShelfSummary({ shelf }: { shelf: Shelf }) {
  const credit = shelf.credit?.names.join(" and ") || "Various authors";
  const total = shelf.catalogue_total ?? shelf.total;
  const saved = shelf.counts.saved ?? 0;
  const current = (shelf.counts.direct ?? 0) + (shelf.counts.contained ?? 0);
  const matched = current + saved;
  const n = (value: number) => value.toLocaleString();
  let summary: string;
  if (
    shelf.truncated ||
    shelf.counts_complete === false ||
    shelf.total_is_lower_bound
  ) {
    summary = `${n(total)} catalogue titles; ${n(shelf.inspected ?? shelf.works.length)}${shelf.total_is_lower_bound ? "" : ` of ${n(shelf.total)}`} entries read`;
  } else if (current && saved) {
    summary = `${n(matched)} of ${n(total)} shelved: ${n(current)} with a matched copy and ${n(saved)} with a saved match`;
  } else {
    const clause = saved ? "with a saved match" : "with a matched copy";
    summary =
      matched === total && shelf.total === total
        ? `${n(total)} shelved, ${total === 1 ? "" : "every one "}${clause}`
        : `${n(matched)} of ${n(total)} shelved ${clause}`;
  }
  return (
    <span className="shelf-context">
      <span className="shelf-credit" title={credit}>
        {credit}
      </span>
      <span aria-hidden="true">{" · "}</span>
      <span className="shelf-count">{summary}</span>
    </span>
  );
}

export function shelfPreview(
  works: LibraryWork[],
  count: number,
  selected?: string,
) {
  const preview = works.slice(0, count);
  const chosen = works.find((work) => work.id === selected);
  if (chosen && !preview.includes(chosen)) preview.splice(count - 1, 1, chosen);
  return preview;
}

export function Library({
  route,
  navigate,
  openCatalogue,
}: {
  route: LibraryRoute;
  navigate: (next: Partial<LibraryRoute>, push?: boolean) => void;
  openCatalogue?: (
    selection: CatalogueSelection,
    origin: LibraryReturn,
  ) => void;
}) {
  const [search, setSearch] = useState(route.lq);
  const [searchHost, setSearchHost] = useState<Element | null>(null);
  const [generation, setGeneration] = useState(0);
  const [selectedShelf, setSelectedShelf] = useState<string | null>(
    route.ls || null,
  );
  const focused = route.ld === "1";
  const room = useRef<HTMLElement>(null);
  const [columns, setColumns] = useState(3);
  const [desktop, setDesktop] = useState(
    () =>
      typeof matchMedia !== "function" ||
      matchMedia("(min-width: 960px) and (min-height: 680px)").matches,
  );
  const [orderNotice, setOrderNotice] = useState("");
  const [optionsOpen, setOptionsOpen] = useState(
    () =>
      typeof matchMedia !== "function" ||
      matchMedia("(min-width: 960px) and (min-height: 680px)").matches,
  );
  const browseView = useBrowseView();
  const results = useRef<HTMLParagraphElement>(null);
  const focusResults = useRef(false);
  const restoreRetryFocus = useRef(false);
  const restoredReturn = useRef(false);
  const returnPlace = useRef<{
    id: string;
    scroll: number;
    shelfScroll: Record<string, number>;
  }>({ id: "", scroll: 0, shelfScroll: {} });
  function shelfScroll() {
    return Object.fromEntries(
      [...document.querySelectorAll<HTMLElement>(".series-shelf")].map(
        (shelf) => [
          shelf.dataset.shelf!,
          shelf.querySelector<HTMLElement>(".shelf-row")?.scrollLeft ?? 0,
        ],
      ),
    );
  }
  const client = useQueryClient();
  useEffect(
    () => setSearchHost(document.getElementById("workspace-search-slot")),
    [],
  );
  useEffect(() => setSearch(route.lq), [route.lq]);
  useEffect(() => {
    const node = room.current;
    if (!node) return;
    const resize = (width: number) =>
      setColumns(width >= 1280 ? 5 : width >= 1100 ? 4 : 3);
    resize(node.getBoundingClientRect().width);
    if (typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(([entry]) =>
      resize(entry.contentRect.width),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const media = matchMedia("(min-width: 960px) and (min-height: 680px)");
    const changed = () => {
      setOptionsOpen(media.matches);
      setDesktop(media.matches);
    };
    media.addEventListener?.("change", changed);
    return () => media.removeEventListener?.("change", changed);
  }, []);
  useEffect(() => setSelectedShelf(route.ls || null), [route.ls]);
  const catalogue = useQuery({
    queryKey: ["catalogue-status"],
    queryFn: ({ signal }) => api<CataloguePin>("catalogue", { signal }),
    retry: false,
    staleTime: Infinity,
  });
  const isSeries = route.lx === "series";
  const standalone = route.lg === "standalone";
  const pinnedListing = isSeries || standalone;
  const pin = catalogue.data;
  const scope = JSON.stringify([
    route.lq,
    route.lo,
    route.lx,
    route.lg,
    pin?.version,
    pin?.sha256,
  ]);
  const [lastReady, setLastReady] = useState<{
    scope: string;
    data: LibraryListing;
    catalogue?: CataloguePin;
    route: LibraryRoute;
  }>();
  const intent = JSON.stringify([scope, route.lp, generation]);
  const activeIntent = useRef(intent);
  activeIntent.current = intent;
  const budget = useRef({ intent, spent: false });
  if (budget.current.intent !== intent)
    budget.current = { intent, spent: false };
  const expiredForClient = expiredChecks.get(client) ?? new Set<string>();
  expiredChecks.set(client, expiredForClient);
  const [expired, setExpired] = useState<string[]>(() => [...expiredForClient]);
  const [recovery, setRecovery] = useState<{
    intent: string;
    phase: "refreshing" | "held";
    reason?: "version_mismatch" | "truncated" | "not_configured";
  }>();
  const listing = useQuery({
    queryKey: key(route, generation, pin),
    enabled:
      !catalogue.isPending &&
      (!pinnedListing || (pin?.status === "ready" && !pin.fixture)),
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({
        q: route.lq,
        page: String(route.lp),
        ownership: route.lo,
        snapshot: route.lt,
      });
      if (pinnedListing) {
        params.set("version", pin!.version!);
        params.set("sha256", pin!.sha256!);
        if (standalone) params.set("group", "standalone");
      } else params.set("sort", route.lx);
      const active = () => activeIntent.current === intent && !signal.aborted;
      const read = () =>
        api<LibraryListing | { status: "not_configured" }>(
          `library${pinnedListing ? "/shelves" : ""}?${params}`,
          { signal },
        );
      const retire = (snapshots: (string | undefined)[]) => {
        const retired = snapshots.filter((value): value is string => !!value);
        retired.forEach((snapshot) => expiredForClient.add(snapshot));
        const cachedTokens = new Set<string>(retired);
        for (const query of client
          .getQueryCache()
          .findAll({ queryKey: ["library"] })) {
          const cached = query.state.data as LibraryListing | undefined;
          if (cached?.snapshot) cachedTokens.add(cached.snapshot);
          if (typeof query.queryKey[5] === "string")
            cachedTokens.add(query.queryKey[5]);
        }
        for (const snapshot of expiredForClient)
          if (!cachedTokens.has(snapshot)) expiredForClient.delete(snapshot);
        setExpired([...expiredForClient]);
        client.setQueriesData<LibraryListing | { status: "not_configured" }>(
          { queryKey: ["library"] },
          (cached) =>
            cached &&
            cached.status !== "not_configured" &&
            retired.includes(cached.snapshot)
              ? historicalListing(cached)
              : cached,
        );
      };
      let response: LibraryListing | { status: "not_configured" };
      try {
        response = await read();
      } catch (error) {
        if (
          !(error instanceof ApiError) ||
          error.status !== 409 ||
          error.code !== "library_check_changed" ||
          !active()
        )
          throw error;
        retire([route.lt, lastReady?.data.snapshot]);
        if (budget.current.spent) {
          setRecovery({ intent, phase: "held" });
          throw error;
        }
        budget.current.spent = true;
        setRecovery({ intent, phase: "refreshing" });
        params.set("snapshot", "");
        try {
          response = await read();
        } catch (retryError) {
          if (active()) setRecovery({ intent, phase: "held" });
          throw retryError;
        }
      }
      if (
        active() &&
        response.status !== "not_configured" &&
        lastReady &&
        response.snapshot !== lastReady.data.snapshot
      )
        retire([lastReady.data.snapshot]);
      if (
        active() &&
        budget.current.spent &&
        (response.status === "not_configured" ||
          response.status === "version_mismatch" ||
          response.truncated)
      ) {
        setRecovery({
          intent,
          phase: "held",
          reason:
            response.status === "not_configured" ||
            response.status === "version_mismatch"
              ? response.status
              : "truncated",
        });
      }
      if (
        active() &&
        response.status === "ready" &&
        !response.loading &&
        !response.truncated
      ) {
        budget.current.spent = false;
        setRecovery(undefined);
        if (expiredForClient.delete(response.snapshot))
          setExpired([...expiredForClient]);
      }
      return response;
    },
    retry: false,
    staleTime: (query) =>
      query.state.data &&
      query.state.data.status !== "not_configured" &&
      expiredForClient.has(query.state.data.snapshot)
        ? 0
        : Infinity,
    refetchOnMount: "always",
    refetchOnReconnect: "always",
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.data?.status !== "not_configured" &&
      !query.state.data?.truncated &&
      (query.state.data?.status === "preparing" ||
        ((query.state.data?.status === "ready" ||
          query.state.data?.status === "loading") &&
          query.state.data.loading))
        ? 2500
        : false,
  });
  const incoming =
    listing.data &&
    listing.data.status !== "not_configured" &&
    (!listing.isError ||
      (listing.data.status === "ready" &&
        expired.includes(listing.data.snapshot)))
      ? listing.data
      : undefined;
  useEffect(() => {
    if (
      incoming?.status === "ready" &&
      !incoming.loading &&
      !incoming.truncated
    )
      setLastReady({
        scope,
        data: expired.includes(incoming.snapshot)
          ? historicalListing(incoming)
          : incoming,
        catalogue: pin,
        route: { ...route, lp: incoming.page, lt: incoming.snapshot },
      });
  }, [incoming, scope, expired]);
  const preparing = incoming?.status === "preparing";
  const recovering = recovery?.intent === intent;
  const recoveryHeld = recovering && recovery.phase === "held";
  const sameRetainedPin =
    lastReady?.catalogue?.version === pin?.version &&
    lastReady?.catalogue?.sha256 === pin?.sha256 &&
    lastReady?.catalogue?.status === pin?.status &&
    lastReady?.catalogue?.fixture === pin?.fixture;
  const retainedRecovery =
    !!lastReady &&
    sameRetainedPin &&
    lastReady.scope === scope &&
    expired.includes(lastReady.data.snapshot) &&
    (!incoming ||
      incoming.status !== "ready" ||
      incoming.truncated ||
      incoming.loading ||
      expired.includes(incoming.snapshot));
  const retaining =
    !!lastReady &&
    ((lastReady.scope === scope && (preparing || listing.isPending)) ||
      retainedRecovery);
  const rawData = retaining ? lastReady!.data : incoming;
  const historical = !!rawData && expired.includes(rawData.snapshot);
  const data = rawData && historical ? historicalListing(rawData) : rawData;
  const displayedRoute = retaining
    ? lastReady!.route
    : { ...route, lp: data?.page ?? route.lp, lt: data?.snapshot ?? route.lt };
  const sameCatalogue =
    pin?.status === "ready" &&
    !pin.fixture &&
    pin.version === data?.catalogue_version &&
    (!data?.catalogue_snapshot ||
      (data.catalogue_snapshot.version === pin.version &&
        data.catalogue_snapshot.sha256 === pin.sha256)) &&
    (!retaining || sameRetainedPin) &&
    !!pin.sha256;
  const usable = data?.status === "ready" && !data.truncated;
  const works = usable ? data.works : [];
  const savedReturn: LibraryReturn | undefined = history.state?.libraryReturn;
  const heldReturn =
    !!savedReturn &&
    (!savedReturn.catalogue ||
      savedReturn.catalogue.version !== pin?.version ||
      savedReturn.catalogue.sha256 !== pin?.sha256);
  const selected =
    works.find(
      (work) =>
        work.id === route.lw && !(heldReturn && route.lw === savedReturn.work),
    ) ?? (desktop ? works[0] : undefined);
  useEffect(() => {
    if (
      incoming &&
      !incoming.loading &&
      incoming.status === "ready" &&
      !incoming.truncated &&
      !expired.includes(incoming.snapshot)
    ) {
      const saved: LibraryReturn | undefined = history.state?.libraryReturn;
      const returnPin = saved?.catalogue;
      if (
        saved &&
        pin?.status === "ready" &&
        !pin.fixture &&
        returnPin?.version === pin?.version &&
        returnPin?.sha256 === pin?.sha256 &&
        !!pin?.sha256 &&
        incoming.catalogue_version === pin.version &&
        saved.route.lt !== incoming.snapshot &&
        ["lq", "lp", "lo", "lx", "lg"].every(
          (field) =>
            (saved.route[field as keyof LibraryRoute] ?? "") ===
            (route[field as keyof LibraryRoute] ?? ""),
        ) &&
        incoming.works.some((work) => work.id === saved.work)
      ) {
        history.replaceState(
          {
            ...history.state,
            libraryReturn: {
              ...saved,
              route: { ...saved.route, lt: incoming.snapshot },
              catalogue: { version: pin.version, sha256: pin.sha256 },
            },
          },
          "",
        );
      }
    }
  }, [incoming, route, pin, expired]);
  useEffect(() => {
    if (
      incoming &&
      (!incoming.loading || recovering) &&
      incoming.status !== "version_mismatch" &&
      incoming.snapshot !== route.lt &&
      !expired.includes(incoming.snapshot)
    ) {
      client.setQueryData(
        key({ ...route, lt: incoming.snapshot }, generation, pin),
        incoming,
      );
      navigate({ lt: incoming.snapshot });
    }
  }, [incoming, route, generation, pin, expired]);
  useEffect(() => {
    if (data && !data.loading && !retaining && focusResults.current) {
      results.current?.focus();
      focusResults.current = false;
    }
  }, [data, retaining]);
  useEffect(() => {
    if (
      !restoreRetryFocus.current ||
      listing.isFetching ||
      (!listing.error && !(incoming?.status === "ready" && !incoming.loading))
    )
      return;
    if (
      document.activeElement !== document.body &&
      !document.activeElement?.matches(".work-title, .list-summary")
    ) {
      restoreRetryFocus.current = false;
      return;
    }
    const target = listing.error
      ? room.current?.querySelector<HTMLElement>('[role="alert"] button')
      : focused && !desktop
        ? (room.current?.querySelector<HTMLElement>(
            ".library-detail .work-title",
          ) ?? results.current)
        : results.current;
    if (!target) return;
    target.focus({ preventScroll: true });
    restoreRetryFocus.current = false;
  }, [listing.isFetching, listing.error, incoming, focused, desktop]);
  useEffect(() => {
    if (!usable || !data || data.loading || restoredReturn.current) return;
    const saved: LibraryReturn | undefined = history.state?.libraryReturn;
    if (
      !saved ||
      heldReturn ||
      !data.works.some((work) => work.id === saved.work) ||
      ["lq", "lp", "lo", "lx", "lt", "lg"].some(
        (field) =>
          saved.route[field as keyof LibraryRoute] !==
          route[field as keyof LibraryRoute],
      ) ||
      saved.route.lt !== data.snapshot
    )
      return;
    restoredReturn.current = true;
    setSelectedShelf(saved.shelf ?? null);
    returnPlace.current = {
      id: `library-${saved.shelf ?? "none"}-${saved.work}`,
      scroll: saved.scroll,
      shelfScroll: saved.shelfScroll ?? {},
    };
    if (
      saved.work &&
      (route.lw !== saved.work ||
        (saved.shelf && route.ls !== saved.shelf) ||
        route.ld === "1")
    )
      navigate({ lw: saved.work, ls: saved.shelf ?? "", ld: "" });
    requestAnimationFrame(() => {
      for (const shelf of document.querySelectorAll<HTMLElement>(
        ".series-shelf",
      )) {
        const row = shelf.querySelector<HTMLElement>(".shelf-row");
        if (row && saved.shelfScroll?.[shelf.dataset.shelf!] !== undefined)
          row.scrollLeft = saved.shelfScroll[shelf.dataset.shelf!];
      }
      (
        document.getElementById(saved.focusId ?? "") ??
        document.getElementById(
          `library-${saved.shelf ?? "none"}-${saved.work}`,
        ) ??
        [...document.querySelectorAll<HTMLButtonElement>(".shelf-entry")].find(
          (entry) => entry.dataset.work === saved.work,
        )
      )?.focus({ preventScroll: true });
      window.scrollTo(0, saved.scroll);
    });
  }, [data, route]);
  function filter(next: Partial<LibraryRoute>) {
    restoreRetryFocus.current = false;
    focusResults.current = true;
    navigate({ ...next, lw: "", ls: "", ld: "" }, true);
  }
  function order(value: string) {
    try {
      localStorage.setItem(orderKey, value);
      setOrderNotice("");
    } catch {
      setOrderNotice("Order changed; preference not saved.");
    }
    filter({ lx: value, lg: "", lp: 1 });
  }
  function allStandalone(event: React.MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    history.replaceState(
      {
        ...history.state,
        libraryReturn: {
          route: displayedRoute,
          work: selected?.id ?? "",
          scroll: window.scrollY,
          open: [],
          shelf: activeShelf,
          shelfScroll: shelfScroll(),
          focusId: "standalone-all",
          catalogue:
            pin?.version && pin.sha256
              ? { version: pin.version, sha256: pin.sha256 }
              : undefined,
        } satisfies LibraryReturn,
      },
      "",
    );
    restoredReturn.current = false;
    filter({ lx: "title", lg: "standalone", lp: 1 });
  }
  function reload() {
    const fromFailure = !!document.activeElement?.closest('[role="alert"]');
    restoreRetryFocus.current = fromFailure;
    setGeneration((old) => old + 1);
    navigate({ lt: "" });
    if (fromFailure)
      requestAnimationFrame(() => {
        if (!restoreRetryFocus.current) return;
        (focused && !desktop
          ? (room.current?.querySelector<HTMLElement>(
              ".library-detail .work-title",
            ) ?? results.current)
          : results.current
        )?.focus({ preventScroll: true });
      });
  }
  function back() {
    navigate({ ld: "" });
    requestAnimationFrame(() => {
      (
        document.getElementById(returnPlace.current.id) ??
        [...document.querySelectorAll<HTMLButtonElement>(".shelf-entry")].find(
          (entry) => entry.dataset.work === selected?.id,
        )
      )?.focus({ preventScroll: true });
      window.scrollTo(0, returnPlace.current.scroll);
    });
  }
  function choose(
    work: LibraryWork,
    shelfId: string | null,
    element: HTMLButtonElement,
  ) {
    restoreRetryFocus.current = false;
    if (heldReturn) {
      const { libraryReturn: _oldReturn, ...state } = history.state ?? {};
      history.replaceState(state, "");
    }
    returnPlace.current = {
      id: element.id,
      scroll: window.scrollY,
      shelfScroll: shelfScroll(),
    };
    setSelectedShelf(shelfId ?? "none");
    navigate(
      {
        ...(retaining ? displayedRoute : {}),
        lw: work.id,
        ls: shelfId ?? "none",
        ld: "1",
      },
      true,
    );
    requestAnimationFrame(() => {
      if (
        typeof matchMedia === "function" &&
        !matchMedia("(min-width: 960px) and (min-height: 680px)").matches
      ) {
        document
          .querySelector<HTMLElement>(".library-detail .work-title")
          ?.focus({ preventScroll: true });
        window.scrollTo(0, 0);
      }
      document.querySelector(".library-detail")?.scrollTo?.(0, 0);
    });
  }
  const artworkIds = [...new Set(works.map((work) => work.id))].slice(0, 24);
  const artwork = useQuery({
    queryKey: ["library-artwork", pin?.version, pin?.sha256, artworkIds],
    enabled: sameCatalogue && artworkIds.length > 0,
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        version: pin!.version!,
        sha256: pin!.sha256!,
      });
      artworkIds.forEach((id) => params.append("work", id));
      return api<{
        snapshot: { version: string; sha256: string };
        covers: Record<string, Cover>;
      }>(`catalogue/covers?${params}`, { signal });
    },
    retry: false,
    staleTime: Infinity,
  });
  const coverMap =
    sameCatalogue &&
    artwork.data?.snapshot?.version === data?.catalogue_version &&
    artwork.data?.snapshot?.sha256 === pin?.sha256
      ? artwork.data!.covers
      : {};
  function catalogueHref(selection: { cw?: string; cs?: string }) {
    const params = new URLSearchParams(location.search);
    Object.entries({
      ...displayedRoute,
      view: "catalogue",
      cb: "works",
      cq: "",
      cp: "1",
      cw: "",
      cs: "",
      ca: "",
      cv: data?.catalogue_version ?? "",
      ch: pin?.sha256 ?? "",
      ...selection,
    }).forEach(([name, value]) => params.set(name, String(value)));
    return `${location.pathname}?${params}`;
  }
  function followCatalogue(
    event: React.MouseEvent<HTMLAnchorElement>,
    work: string,
    selection: { cw?: string; cs?: string },
  ) {
    if (
      !openCatalogue ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      event.defaultPrevented
    )
      return;
    event.preventDefault();
    const phoneDetail =
      focused &&
      typeof matchMedia === "function" &&
      !matchMedia("(min-width: 960px) and (min-height: 680px)").matches;
    openCatalogue(
      { ...selection, cv: data!.catalogue_version!, ch: pin!.sha256! },
      {
        route: { ...displayedRoute, lw: work, lt: data!.snapshot },
        work,
        scroll: phoneDetail ? returnPlace.current.scroll : window.scrollY,
        open: [work],
        shelf: activeShelf,
        shelfScroll: phoneDetail
          ? returnPlace.current.shelfScroll
          : shelfScroll(),
        catalogue: { version: data!.catalogue_version!, sha256: pin!.sha256! },
      },
    );
  }
  const groups: Shelf[] = isSeries
    ? (data?.shelves ?? [])
    : [
        {
          id: null,
          name: "Library matches",
          total: data?.total ?? 0,
          catalogue_total: null,
          works,
          counts: {},
          position_counts: { numbered: 0, zero: 0, unpositioned: 0 },
        },
      ];
  const selectedGroup =
    groups.find(
      (group) =>
        !heldReturn &&
        (group.id ?? "none") === selectedShelf &&
        group.works.some((work) => work.id === selected?.id),
    ) ??
    groups.find((group) =>
      group.works.some((work) => work.id === selected?.id),
    );
  const activeShelf = selectedGroup ? (selectedGroup.id ?? "none") : undefined;
  const pages = data
    ? Math.max(
        1,
        Math.ceil(
          (isSeries ? (data.series_total ?? 0) : data.total) / data.page_size,
        ),
      )
    : 1;
  const phoneFeedback = focused && !desktop && !!selected;
  const recoveryFeedback = (
    <>
      {listing.error && (
        <div className="error" role="alert">
          <p>
            {recovering
              ? `The library check changed again or could not be refreshed. ${lastReady ? "Saved results remain available; current copies are unconfirmed." : "No current results are available."}`
              : listing.error.message}
          </p>
          {recovering && <p>{listing.error.message}</p>}
          {recovering ||
          (listing.error instanceof ApiError &&
            listing.error.status === 409) ? (
            <button onClick={reload} disabled={listing.isFetching}>
              Reload library
            </button>
          ) : (
            <button onClick={() => void listing.refetch()}>
              Retry library request
            </button>
          )}
        </div>
      )}
      {recoveryHeld && !listing.error && (
        <div className="error" role="alert">
          <p>
            {recovery.reason === "version_mismatch"
              ? "The current library check uses a different catalogue version."
              : recovery.reason === "truncated"
                ? "The current shelves read exceeded its limit."
                : "Library Finish is not connected."}{" "}
            {lastReady
              ? "Saved results remain historical; current copies are unconfirmed."
              : "No current results are available."}
          </p>
          {recovery.reason === "truncated" ? (
            <button onClick={() => order("title")}>
              Browse in Title order
            </button>
          ) : (
            <button onClick={reload}>Reload library</button>
          )}
        </div>
      )}
      {recovering && !recoveryHeld && !listing.error && (
        <p className="context-note" role="status">
          The library check changed. Reading the current check without changing
          your search or page…
        </p>
      )}
      {historical && (
        <p className="context-note" role="status">
          Showing saved results from the previous check. Current copies and
          absence are unconfirmed.
        </p>
      )}
    </>
  );
  const searchForm = (
    <form
      role="search"
      aria-label="Library search"
      className="library-search"
      onSubmit={(event) => {
        event.preventDefault();
        filter({ lq: search, lp: 1 });
      }}
    >
      <label className="sr-only" htmlFor="library-search">
        Search your library
      </label>
      <input
        id="library-search"
        type="search"
        value={search}
        maxLength={200}
        onChange={(event) => {
          restoreRetryFocus.current = false;
          setSearch(event.target.value);
        }}
        placeholder="Search titles, authors or series"
      />
      <button type="submit" aria-label="Search library">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="currentColor" />
          <path d="m10 10 4 4" stroke="currentColor" />
        </svg>
      </button>
    </form>
  );
  return (
    <section
      className={`library reading-room browse-${browseView.view} ${focused && selected ? "library-focused" : ""} ${selected ? "has-selected-book" : ""}`}
      ref={room}
      style={{ "--shelf-columns": columns } as React.CSSProperties}
      aria-labelledby="library-heading"
    >
      {searchHost ? createPortal(searchForm, searchHost) : searchForm}
      <div className="library-collection">
        <div className="library-heading">
          <div>
            <h1 id="library-heading">Your library</h1>
            {data && (
              <p
                className="list-summary"
                role="status"
                tabIndex={-1}
                ref={results}
              >
                {data.total.toLocaleString()}{" "}
                {historical
                  ? "titles in the saved view"
                  : route.lo === "all"
                    ? "catalogue titles"
                    : "matching titles"}
              </p>
            )}
          </div>
          {data && (
            <details className="library-context">
              <summary>
                <span className="check-dot" />
                <span>
                  {checkLabel(data.coverage)}
                  <span aria-hidden="true">{" · "}</span>
                </span>
                <span className="check-date">
                  <time dateTime={data.checked_at ?? undefined}>
                    {dateLabel(data.checked_at)}
                  </time>
                  <span aria-hidden="true">{" · "}</span>
                </span>
                <span className="details-label">Details</span>
              </summary>
              <div className="library-check-details">
                <p>
                  {checkLabel(data.coverage)} · {dateLabel(data.checked_at)}
                  {data.loading && " · updating"}
                </p>
                <p>
                  {data.coverage === "complete"
                    ? "Ownership is supported at the recorded check time."
                    : "Unlisted titles may still be in Calibre."}
                </p>
                <p>Catalogue {data.catalogue_version ?? "not yet available"}</p>
                <p className="source-id">{data.snapshot}</p>
                <button
                  className="secondary"
                  onClick={reload}
                  disabled={listing.isFetching}
                >
                  {listing.isFetching ? "Reading library…" : "Reload library"}
                </button>
              </div>
            </details>
          )}
        </div>
        <div className="library-tools">
          <p className="order-description">
            {isSeries
              ? "Shelved by series, in recorded order"
              : route.lx === "author"
                ? "Ordered by author"
                : "Ordered by title"}
          </p>
          <label className="reading-control">
            <span>Order</span>
            <select
              aria-label="Order"
              value={route.lx}
              onChange={(event) => order(event.target.value)}
            >
              <option value="series">Series</option>
              <option value="title">Title</option>
              <option value="author">Author</option>
            </select>
          </label>
          <details
            className="library-options"
            open={optionsOpen}
            onToggle={(event) => {
              if (event.target === event.currentTarget)
                setOptionsOpen(event.currentTarget.open);
            }}
          >
            <summary>
              Filters and view{route.lo !== "owned" && " · applied"}
            </summary>
            <label className="reading-control">
              <span>Copies</span>
              <select
                aria-label="Copies"
                value={route.lo}
                onChange={(event) => filter({ lo: event.target.value, lp: 1 })}
              >
                <option value="owned">All matched</option>
                <option value="direct">Direct matches</option>
                <option value="contained">Inside collections</option>
                <option value="pending">Pending identification</option>
                <option value="all">Whole catalogue</option>
              </select>
            </label>
          </details>
          <BrowseView {...browseView} />
          {orderNotice && <p role="status">{orderNotice}</p>}
        </div>
        {heldReturn && (
          <p className="context-note" role="status">
            The saved library position has a different or unrecorded catalogue
            fingerprint. Choose a book in the current results to continue.
          </p>
        )}
        {pinnedListing &&
        (catalogue.isError ||
          (pin && (pin.status !== "ready" || pin.fixture))) ? (
          <div className="error" role="alert">
            <p>
              Series shelves need the published catalogue. Title and Author
              order remain available.
            </p>
            {catalogue.isError && (
              <button onClick={() => void catalogue.refetch()}>
                Retry catalogue connection
              </button>
            )}
          </div>
        ) : (
          listing.isPending && <p role="status">Reading library…</p>
        )}
        {listing.data?.status === "not_configured" && (
          <p className="context-note">Library not connected</p>
        )}
        {!phoneFeedback && recoveryFeedback}
        {incoming?.status === "version_mismatch" && !recoveryHeld && (
          <div className="error" role="alert">
            <p>
              Library check uses a different catalogue version. No matches have
              been attached to these shelves.
            </p>
            <button onClick={reload}>Reload library</button>
          </div>
        )}
        {incoming?.truncated && !recoveryHeld && (
          <div className="error" role="alert">
            <p>
              The library exceeds the bounded shelves read. Choose Title or
              Author order to browse all results.
            </p>
            <button onClick={() => order("title")}>
              Browse in Title order
            </button>
          </div>
        )}
        {data?.unlinked_total ? (
          <p className="context-note">
            {data.unlinked_total} library{" "}
            {data.unlinked_total === 1 ? "title has" : "titles have"} no
            identity in this pinned catalogue. Title and Author order retain
            those records.
          </p>
        ) : null}
        {preparing && (
          <p className="context-note" role="status">
            Preparing shelves…
          </p>
        )}
        {retaining && !historical && (
          <p className="context-note" role="status">
            Showing the previous page until the new shelves are ready.
          </p>
        )}
        {standalone && usable && !retaining && (
          <p className="context-note" role="status">
            Showing all {data!.total.toLocaleString()} standalone and collected
            titles
          </p>
        )}
        {data?.loading && works.length === 0 && (
          <p className="context-note" role="status">
            Library Finish is loading · reload shortly
          </p>
        )}
        {usable && !retaining && !data!.loading && data!.total === 0 && (
          <div className="library-empty">
            <h2>No matches for these filters.</h2>
            {data!.coverage !== "complete" && (
              <p>{checkLabel(data!.coverage)} · some copies may be unlisted.</p>
            )}
            <button
              onClick={() => {
                setSearch("");
                filter({ lq: "", lo: "owned", lx: "series", lg: "", lp: 1 });
              }}
            >
              Clear filters
            </button>
            {route.lp > 1 && (
              <button onClick={() => filter({ lp: 1 })}>First page</button>
            )}
          </div>
        )}
        {usable &&
          !retaining &&
          !data!.loading &&
          data!.total > 0 &&
          works.length === 0 &&
          (!isSeries || groups.length === 0) && (
            <div className="library-empty">
              <h2>No results on this page.</h2>
              <button onClick={() => filter({ lp: 1 })}>First page</button>
            </div>
          )}
        {selected && desktop && (
          <a
            className="skip-selected skip-shelves"
            href="#selected-book"
            onClick={(event) => {
              event.preventDefault();
              document.getElementById("selected-book")?.focus();
            }}
          >
            Skip to selected book
          </a>
        )}
        <div
          className={`shelves-display${retaining && !historical ? " preparing" : ""}`}
          aria-busy={!!retaining}
          inert={!!retaining && !historical}
        >
          {usable &&
            groups.map((shelf) => (
              <section
                className="series-shelf"
                data-shelf={shelf.id ?? "none"}
                key={shelf.id ?? "unseries"}
                aria-label={shelf.name}
              >
                {isSeries && (
                  <header className="shelf-heading">
                    <h2>
                      <SeriesName name={shelf.name} />
                    </h2>
                    <ShelfSummary shelf={shelf} />
                    {sameCatalogue && shelf.id && (
                      <a
                        href={catalogueHref({ cs: shelf.id })}
                        onClick={(event) =>
                          followCatalogue(event, selected?.id ?? "", {
                            cs: shelf.id!,
                          })
                        }
                      >
                        All{" "}
                        {(
                          shelf.catalogue_total ?? shelf.total
                        ).toLocaleString()}{" "}
                        →
                      </a>
                    )}
                    {shelf.id === null && (
                      <a
                        id="standalone-all"
                        href={`?${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(location.search)), lx: "title", lg: "standalone", lp: "1", lq: route.lq, lo: route.lo })}`}
                        onClick={allStandalone}
                      >
                        All {shelf.total.toLocaleString()} →
                      </a>
                    )}
                  </header>
                )}
                <ol
                  className="shelf-row"
                  aria-label={
                    isSeries
                      ? `${shelf.name} in recorded order`
                      : "Library matches"
                  }
                >
                  {(isSeries && browseView.view === "shelves"
                    ? shelfPreview(
                        shelf.works,
                        desktop ? columns : shelf.works.length,
                        selected?.id,
                      )
                    : shelf.works
                  ).map((work) => (
                    <li key={work.id}>
                      <button
                        className={`shelf-entry ${work.state}`}
                        id={`library-${shelf.id ?? "none"}-${work.id}`}
                        data-work={work.id}
                        aria-pressed={
                          selected?.id === work.id &&
                          activeShelf === (shelf.id ?? "none")
                        }
                        onClick={(event) =>
                          choose(work, shelf.id, event.currentTarget)
                        }
                      >
                        <LibraryBookArt
                          work={work}
                          cover={coverMap[work.id]}
                          seriesId={shelf.id}
                        />
                        <span className="shelf-caption">
                          <span className="shelf-position">
                            {positionLabel(work, shelf.id)}
                          </span>
                          <span className="sr-only">, </span>
                          <strong>{work.title}</strong>
                          <span className="sr-only">.</span>{" "}
                          <span className="book-author">
                            {shelfCredits(work.authors)}
                          </span>
                          <span className="sr-only">.</span>{" "}
                          <span className={`library-state ${work.state}`}>
                            <span className="status-dot" />
                            {savedMatch(work)
                              ? "Saved match"
                              : matchLabels[work.state]}
                          </span>
                          <span className="sr-only">.</span>
                          {(work.shelf_alternates ?? 0) > 0 && (
                            <span className="position-alternates">
                              +{work.shelf_alternates} at this position
                              <span className="sr-only">.</span>
                            </span>
                          )}
                          {work.candidates.length > 0 && (
                            <span className="candidate-count">
                              {work.candidates.length}{" "}
                              {work.candidates.every(
                                (candidate) => candidate.stage === "inbox",
                              )
                                ? "inbox"
                                : "incoming"}{" "}
                              {work.candidates.length === 1
                                ? "candidate"
                                : "candidates"}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
                {shelf.prefix_complete === false && (
                  <p className="context-note">
                    The bounded read could not establish the first works in
                    recorded order.{" "}
                    {shelf.id
                      ? "Open the full series to continue."
                      : "Choose Title or Author order to inspect these records."}
                  </p>
                )}
              </section>
            ))}
        </div>
        {selected && desktop && (
          <a
            className="skip-selected"
            href="#selected-book"
            onClick={(event) => {
              event.preventDefault();
              document.getElementById("selected-book")?.focus();
            }}
          >
            Skip to selected book
          </a>
        )}
        {usable && data!.total > 0 && (
          <nav className="pagination" aria-label="Library pages">
            <button
              disabled={
                (!!retaining && !historical) || data!.loading || route.lp <= 1
              }
              onClick={() => filter({ lp: route.lp - 1 })}
            >
              Previous page
            </button>
            <span>
              Page {data!.page} of {pages}
              {isSeries &&
                ` · ${data!.series_total} ${data!.series_scope === "catalogue" ? "catalogue series" : "shelves"}`}
            </span>
            <button
              disabled={
                (!!retaining && !historical) ||
                data!.loading ||
                route.lp >= pages
              }
              onClick={() => filter({ lp: route.lp + 1 })}
            >
              Next page
            </button>
          </nav>
        )}
      </div>
      {selected && data && (
        <aside className="library-detail" aria-label="Selected book">
          {phoneFeedback && recoveryFeedback}
          <LibraryBookDetails
            key={`${selected.id}:${pin?.version}:${pin?.sha256}`}
            workId={selected.id}
            version={sameCatalogue ? pin!.version! : ""}
            sha256={sameCatalogue ? pin!.sha256! : ""}
            enabled
            renderBook={(book) => (
              <LibraryBookPane
                key={selected.id}
                work={selected}
                book={book}
                data={data}
                art={coverMap[selected.id]}
                seriesId={activeShelf === "none" ? null : activeShelf}
                pin={sameCatalogue ? pin : undefined}
                catalogueMismatch={pin?.status === "ready" && !sameCatalogue}
                follow={followCatalogue}
                href={catalogueHref}
                back={back}
              />
            )}
          />
        </aside>
      )}
    </section>
  );
}
