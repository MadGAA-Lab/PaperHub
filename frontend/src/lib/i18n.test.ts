import { describe, expect, it } from "vitest";
import i18n from "./i18n";

describe("i18n", () => {
  it("defaults to en and resolves a common key", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("common:appName")).toBe("PaperHub");
  });

  it("switches to zh-TW", async () => {
    await i18n.changeLanguage("zh-TW");
    expect(i18n.t("common:language")).toBe("語言");
    await i18n.changeLanguage("en");
  });
});
