import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/eb-garamond/400.css";
import "@fontsource/eb-garamond/400-italic.css";
import "@fontsource/eb-garamond/600.css";
import "@fontsource/cinzel/600.css";
import "@fontsource/cinzel/700.css";
import "@fontsource/noto-serif-hebrew/400.css";
import "@fontsource/jetbrains-mono/400.css";
import "./codex.css";
import CodexApp from "./CodexApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CodexApp />
  </StrictMode>,
);
