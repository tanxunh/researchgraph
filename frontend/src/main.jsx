import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp } from "antd";
import enUS from "antd/locale/en_US";
import { BrowserRouter } from "react-router-dom";
import "antd/dist/reset.css";
import App from "./App.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ConfigProvider
      locale={enUS}
      theme={{
        token: {
          colorPrimary: "#25645e",
          colorLink: "#25645e",
          colorLinkHover: "#1c514c",
          colorSuccess: "#28714e",
          colorWarning: "#956518",
          colorError: "#b34040",
          colorText: "#202e3c",
          colorTextSecondary: "#5e6d7a",
          colorBorder: "#dde3e8",
          borderRadius: 8,
          fontFamily:
            'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      }}
    >
      <AntApp>
        <BrowserRouter><App /></BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
