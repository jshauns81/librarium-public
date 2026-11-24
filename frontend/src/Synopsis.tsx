import React, { useId, useLayoutEffect, useRef, useState } from "react";

export function Synopsis({
  text,
  headingLevel = 3,
  readingRoom = false,
}: {
  text: string;
  headingLevel?: 2 | 3;
  readingRoom?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(text.length > 550);
  const paragraph = useRef<HTMLParagraphElement>(null);
  const id = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  useLayoutEffect(() => {
    if (expanded || !paragraph.current) return;
    const element = paragraph.current;
    function measure() {
      if (element.clientHeight > 0)
        setTruncated(element.scrollHeight > element.clientHeight + 1);
    }
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [text, expanded]);
  return (
    <section className="synopsis detail-section" aria-label="About this book">
      <Heading className={readingRoom ? "sr-only" : undefined}>
        About this book
      </Heading>
      <p
        ref={paragraph}
        id={id}
        className={!expanded ? "synopsis-preview" : undefined}
      >
        {text}
      </p>
      {(truncated || expanded) && (
        <button
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded
            ? "Show less"
            : readingRoom
              ? "Read the full synopsis"
              : "Read full synopsis"}
        </button>
      )}
    </section>
  );
}
