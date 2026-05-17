import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/layout/ThemeToggle";

function renderWithProvider() {
  return render(
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    localStorage.clear();
  });

  it("renders with an accessible label", () => {
    renderWithProvider();
    expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  });

  it("toggles the dark class on the html element on click", async () => {
    renderWithProvider();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /theme/i }));
    // next-themes updates classList asynchronously after the resolved theme settles.
    await waitFor(() =>
      expect(document.documentElement.classList.contains("dark")).toBe(true),
    );
  });
});
