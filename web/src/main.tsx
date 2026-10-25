import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { tidyReloadParam } from "./lib/updates";
import "./styles/theme.css";
import "./styles/components.css";

tidyReloadParam();
const root = document.getElementById("root");
if (!root) throw new Error("No #root element");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
