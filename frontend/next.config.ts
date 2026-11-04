import type { NextConfig } from "next";

// Exportação estática: a interface é servida pelo próprio backend (mesma origem) ou por
// qualquer hospedagem estática (Netlify), apontando para a API via NEXT_PUBLIC_API_URL
// ou pela configuração "Servidor" na tela de login.
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
};

export default config;
