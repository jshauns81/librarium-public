// jsdom has no viewport scrolling or canvas rendering. Real-browser proof covers both.
if (typeof window !== "undefined") {
  window.scrollTo = () => {};
  HTMLCanvasElement.prototype.getContext = () => null;
}
