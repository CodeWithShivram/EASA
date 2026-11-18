import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Source } from "@/lib/api/conversations";

import { AnswerText } from "./AnswerText";

const source = (label: string): Source => ({
  label,
  citation: {
    document_id: "d",
    filename: `${label}.txt`,
    page_number: null,
    section: null,
    chunk_index: 0,
    char_start: 0,
    char_end: 1,
  },
});

describe("AnswerText", () => {
  it("turns known citation markers into buttons and keeps the rest as text", async () => {
    const onCite = vi.fn();
    render(
      <AnswerText
        text="Leave is 25 days [S1] and carry-over 5 [S2] [S9]."
        sources={[source("S1"), source("S2")]}
        onCite={onCite}
      />,
    );

    await userEvent.setup().click(screen.getByRole("button", { name: "Show source S2: S2.txt" }));

    expect(onCite).toHaveBeenCalledWith(expect.objectContaining({ label: "S2" }));
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByText(/\[S9\]/)).toBeInTheDocument(); // no such source: plain text
  });

  it("renders markup in answers as text, never as HTML", () => {
    const { container } = render(
      <AnswerText
        text={'<img src=x onerror="alert(1)"> [S1]'}
        sources={[source("S1")]}
        onCite={vi.fn()}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});
