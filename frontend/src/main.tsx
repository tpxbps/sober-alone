import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import { loadAtmosphere } from './components/lobby/loadAtmosphere';
import { useSettingsStore } from './stores/settingsStore';

if (!location.search && !matchMedia('(pointer: coarse), (prefers-reduced-motion: reduce)').matches && useSettingsStore.getState().lobbyMotionEnabled) {
  void loadAtmosphere().catch(() => {});
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
