import React from "react";
import ReactDOM from "react-dom/client";
import App from "./quality/Workspace";
import "./quality/styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
