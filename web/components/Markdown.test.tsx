import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Markdown from "./Markdown";

describe("Markdown", () => {
  it("renders bold text, lists and tables", () => {
    const html = renderToStaticMarkup(<Markdown text={"A **clowder**.\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |"} />);

    expect(html).toContain("<strong>clowder</strong>");
    expect(html).toContain("<li>one</li>");
    expect(html).toContain("<td>1</td>");
  });

  it("never renders raw HTML or javascript: links from an answer", () => {
    const html = renderToStaticMarkup(<Markdown text={'<img src=x onerror="alert(1)"> [click](javascript:alert(1))'} />);

    expect(html).not.toContain("<img");
    expect(html).not.toContain("javascript:");
  });
});
