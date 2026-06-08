import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import enCommon from "../locales/en/common.json";
import jaCommon from "../locales/ja/common.json";
import zhCNCommon from "../locales/zh-CN/common.json";
import zhTWCommon from "../locales/zh-TW/common.json";

export const SUPPORTED_LANGUAGES = ["en", "zh-TW", "zh-CN", "ja"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const LANGUAGE_ENDONYMS: Record<SupportedLanguage, string> = {
  en: "English",
  "zh-TW": "繁體中文",
  "zh-CN": "简体中文",
  ja: "日本語",
};

// English is the source-of-truth catalog. New namespaces are added here and
// to each locale folder as the string-extraction pass progresses (Task D1).
const resources = {
  en: { common: enCommon },
  "zh-TW": { common: zhTWCommon },
  "zh-CN": { common: zhCNCommon },
  ja: { common: jaCommon },
} as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LANGUAGES],
    ns: ["common"],
    defaultNS: "common",
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "paperhub-lang",
      caches: ["localStorage"],
    },
  });

export default i18n;
