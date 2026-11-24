// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BrowseView, useBrowseView } from "../src/BrowseView";
import { BookCover } from "../src/BookCover";
import { Synopsis } from "../src/Synopsis";

function Browser() {
  const view = useBrowseView();
  return <BrowseView {...view} />;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

it("remembers the chosen browsing presentation across surfaces and follows other tabs", () => {
  const first = render(<Browser />);
  expect(
    screen
      .getByRole("button", { name: "Shelves" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  first.unmount();
  render(<Browser />);
  expect(
    screen.getByRole("button", { name: "List" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent(
    window,
    new StorageEvent("storage", {
      key: "librarium.browse-view",
      newValue: "shelves",
    }),
  );
  expect(
    screen
      .getByRole("button", { name: "Shelves" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("keeps the view usable when preferences cannot be saved", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  render(<Browser />);
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(
    screen.getByRole("button", { name: "List" }).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(screen.getByRole("status").textContent).toBe(
    "View changed; preference not saved.",
  );
});

it("omits absent or failed artwork while retaining the book and retries a different cover", () => {
  const cover = {
    url: "/api/catalogue/covers/" + "a".repeat(64),
    width: 400,
    height: 600,
    sha256: "a".repeat(64),
    media_type: "image/jpeg",
  };
  const view = render(
    <div>
      <BookCover cover={null} />
      <strong>Horus Rising</strong>
    </div>,
  );
  expect(view.container.querySelector("img")).toBeNull();
  view.rerender(
    <div>
      <BookCover cover={cover} />
      <strong>Horus Rising</strong>
    </div>,
  );
  fireEvent.error(view.container.querySelector("img")!);
  expect(view.container.querySelector("img")).toBeNull();
  expect(screen.getByText("Horus Rising")).toBeTruthy();
  view.rerender(
    <div>
      <BookCover
        cover={{ ...cover, url: "/api/catalogue/covers/" + "b".repeat(64) }}
      />
      <strong>Horus Rising</strong>
    </div>,
  );
  expect(view.container.querySelector("img")).toBeTruthy();
});

it("never sends the browser to an untrusted artwork URL", () => {
  const view = render(
    <BookCover
      cover={{
        url: "https://untrusted.example/cover.jpg",
        width: 400,
        height: 600,
        sha256: "a".repeat(64),
        media_type: "image/jpeg",
      }}
    />,
  );
  expect(view.container.querySelector("img")).toBeNull();
});

it("keeps a long synopsis available without burying the work's tools", () => {
  const text = "The fleet waited in silence. ".repeat(40);
  render(<Synopsis text={text} />);
  const expand = screen.getByRole("button", { name: "Read full synopsis" });
  expect(expand.getAttribute("aria-expanded")).toBe("false");
  expect(
    document.getElementById(expand.getAttribute("aria-controls")!)?.textContent,
  ).toBe(text);
  fireEvent.click(expand);
  expect(
    screen
      .getByRole("button", { name: "Show less" })
      .getAttribute("aria-expanded"),
  ).toBe("true");
});

it("offers expansion when a shorter synopsis overflows a narrow reading measure", () => {
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(96);
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(240);
  render(<Synopsis text="Short words can still fill many lines on a phone." />);
  expect(
    screen.getByRole("button", { name: "Read full synopsis" }),
  ).toBeTruthy();
});
