import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/layout/ThemeToggle";

function renderWithProvider(defaultTheme = "light") {
  return render(
    <ThemeProvider attribute="class" defaultTheme={defaultTheme} enableSystem={false}>
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

  it("cycles Light → Dark → System → Light over three clicks", async () => {
    renderWithProvider("light");
    const button = screen.getByRole("button", { name: /theme/i });

    // Start: light — click → dark
    await userEvent.click(button);
    await waitFor(() =>
      expect(document.documentElement.classList.contains("dark")).toBe(true),
    );

    // Dark → system (next-themes with enableSystem=false treats system like light)
    await userEvent.click(button);
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-label", expect.stringContaining("System")),
    );

    // System → light
    await userEvent.click(button);
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-label", expect.stringContaining("Light")),
    );
  });
});
