import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PaperChat from "../PaperChat";

describe("PaperChat image paste", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:clipboard-image"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a pasted clipboard image and enables sending without text", () => {
    render(
      <PaperChat
        taskId="task-1"
        title="A paper"
        selection=""
        clearSelection={vi.fn()}
        open
        onOpenChange={vi.fn()}
        onSource={vi.fn()}
      />,
    );

    const image = new File(["clipboard"], "clipboard.png", { type: "image/png" });
    const item = { kind: "file", type: "image/png", getAsFile: () => image };
    const composer = screen.getByLabelText("问题");
    fireEvent.paste(composer, { clipboardData: { items: [item] } });

    expect(screen.getByAltText("待发送的图片")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
  });
});
