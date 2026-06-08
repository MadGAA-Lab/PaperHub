// frontend/src/store/settings.test.ts
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { API_BASE_URL } from "../lib/api";
import { useSettingsStore } from "./settings";

const server = setupServer(
  http.get(`${API_BASE_URL}/settings`, () =>
    HttpResponse.json({ categories: [{ key: "logging", label: "Logging", free_form: false, suggestions: [], fields: [] }] }),
  ),
);

describe("settings store", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
  afterAll(() => server.close());

  it("open() sets isOpen and fetch loads the config", async () => {
    useSettingsStore.getState().open();
    expect(useSettingsStore.getState().isOpen).toBe(true);
    await useSettingsStore.getState().fetchConfig();
    const firstCat = useSettingsStore.getState().config?.categories[0];
    expect(firstCat?.key).toBe("logging");
    useSettingsStore.getState().close();
    expect(useSettingsStore.getState().isOpen).toBe(false);
  });
});
