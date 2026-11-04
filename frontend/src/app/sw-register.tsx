"use client";

import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator && location.protocol === "https:") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
