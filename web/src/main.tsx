import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Shop from "./Shop";
import Admin from "./Admin";
import "./styles.css";

// Two pages, switched by the URL hash: "#/" is the shop, "#/admin" is the seller dashboard.
function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash.startsWith("#/admin") ? <Admin /> : <Shop />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
