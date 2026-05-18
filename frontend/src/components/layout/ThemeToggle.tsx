import { Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type ThemeChoice = "light" | "dark" | "system";

const NEXT: Record<ThemeChoice, ThemeChoice> = {
  light: "dark",
  dark: "system",
  system: "light",
};

const LABEL: Record<ThemeChoice, string> = {
  light: "Light theme",
  dark: "Dark theme",
  system: "System theme",
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const current = (theme as ThemeChoice | undefined) ?? "system";
  const Icon =
    current === "light" ? Sun : current === "dark" ? Moon : Monitor;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Theme: ${LABEL[current]}. Click to cycle.`}
              onClick={() => setTheme(NEXT[current])}
            />
          }
        >
          <Icon className="h-4 w-4" />
        </TooltipTrigger>
        <TooltipContent>
          <p className="text-sm">{LABEL[current]} (click to cycle)</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
