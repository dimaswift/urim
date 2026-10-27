import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/rajdhani/500.css";
import "@fontsource/rajdhani/600.css";
import "@fontsource/rajdhani/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";
import "@fontsource/noto-serif-hebrew/400.css";
import "@fontsource/noto-serif-hebrew/600.css";
import "./theme.css";
import App from "./App";
import { AppProvider } from "./state";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
