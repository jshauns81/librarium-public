import React from "react";

export function SeriesName({ name }: { name: string }) {
  const parts = name.split("/");
  return (
    <span className="series-text">
      {parts.map((part, index) => (
        <React.Fragment key={index}>
          {part}
          {index < parts.length - 1 && (
            <>
              /<wbr />
            </>
          )}
        </React.Fragment>
      ))}
    </span>
  );
}
