// Types for the parts of the vendored foliate-js engine the reader uses.
// The engine itself is plain JavaScript under vendor/foliate-js.

declare module "@vendor/foliate/epub.js" {
  export type TocItem = {
    label: string;
    href: string;
    subitems?: TocItem[] | null;
  };
  export type FoliateSection = {
    id: string;
    load(): Promise<string>;
    unload(): void;
    size: number;
    linear?: string;
  };
  export type FoliateBook = {
    metadata: { title?: string | Record<string, string>; language?: string };
    rendition?: { layout?: string };
    sections: FoliateSection[];
    toc?: TocItem[];
    dir?: string;
    transformTarget: EventTarget;
    isExternal(href: string): boolean;
    destroy(): void;
  };
  export class EPUB {
    constructor(loader: {
      entries: { filename: string }[];
      loadText(name: string): string | null;
      loadBlob(name: string, type?: string): Blob | null;
      getSize(name: string): number;
    });
    init(): Promise<FoliateBook>;
  }
}

declare module "@vendor/foliate/view.js" {
  import type { FoliateBook, TocItem } from "@vendor/foliate/epub.js";
  export type Relocation = {
    fraction: number;
    section?: { current: number; total: number };
    location?: { current: number; next: number; total: number };
    tocItem?: TocItem | null;
    pageItem?: { label: string } | null;
    cfi: string;
    range?: Range;
  };
  export type Paginator = HTMLElement & {
    goTo(target: { index: number; anchor?: number }): Promise<void>;
    setStyles(styles: string | [string, string]): void;
    getContents(): { index: number; doc: Document }[];
    readonly page: number;
    readonly pages: number;
    readonly primaryIndex: number;
    focusView(): void;
  };
  export class View extends HTMLElement {
    book: FoliateBook;
    renderer: Paginator;
    lastLocation: Relocation | null;
    open(book: FoliateBook): Promise<void>;
    close(): void;
    init(options: {
      lastLocation?: string | null;
      showTextStart?: boolean;
    }): Promise<void>;
    goTo(target: string | number): Promise<unknown>;
    resolveCFI(cfi: string): { index: number; anchor: unknown };
    goLeft(): Promise<void>;
    goRight(): Promise<void>;
    prev(distance?: number): Promise<void>;
    next(distance?: number): Promise<void>;
  }
}
