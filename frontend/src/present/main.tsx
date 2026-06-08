import React from "react";
import ReactDOM from "react-dom/client";
import { I18nextProvider } from "react-i18next";

import { PresentPage } from "./PresentPage";
import i18n from "../lib/i18n";
import "../index.css";

const session = Number(
  new URLSearchParams(window.location.search).get("session"),
);

ReactDOM.createRoot(document.getElementById("present-root")!).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      {Number.isFinite(session) && session > 0 ? (
        <PresentPage sessionId={session} />
      ) : (
        <div style={{ color: "#fff", fontFamily: "sans-serif", padding: 24 }}>
          Missing or invalid <code>?session</code> parameter.
        </div>
      )}
    </I18nextProvider>
  </React.StrictMode>,
);
