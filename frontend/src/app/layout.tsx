import type { Metadata, Viewport } from "next";

import "./globals.css";
import ServiceWorker from "./sw-register";

export const metadata: Metadata = {
  title: "ULTRON — Central de Inteligência",
  description: "Plataforma pessoal de inteligência artificial autônoma, multiagente e autoevolutiva.",
  manifest: "/manifest.webmanifest",
  applicationName: "ULTRON",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "ULTRON" },
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#050b18",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="antialiased">
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
