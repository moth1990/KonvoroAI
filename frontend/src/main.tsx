import "@fontsource/rubik/500.css";
import "@fontsource/rubik/600.css";
import "@fontsource/rubik/700.css";
import "@fontsource/ibm-plex-sans-hebrew/400.css";
import "@fontsource/ibm-plex-sans-hebrew/500.css";
import "@fontsource/ibm-plex-sans-hebrew/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./theme/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { QueryProvider } from "./api/QueryProvider";
import App from "./App";
import { ThemeRoot } from "./theme/ThemeRoot";

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <ThemeRoot>
      <QueryProvider>
        <App />
      </QueryProvider>
    </ThemeRoot>
  </StrictMode>,
);
