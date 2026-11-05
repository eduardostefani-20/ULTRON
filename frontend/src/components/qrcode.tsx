"use client";

import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** QR code desenhado em SVG pelo React (sem innerHTML). Fundo branco para a câmera ler bem no tema escuro. */
export function QrCode({ value, size = 176 }: { value: string; size?: number }) {
  const { d, total } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    const n = qr.getModuleCount();
    const margin = 4;
    let path = "";
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (qr.isDark(r, c)) path += `M${c + margin} ${r + margin}h1v1h-1z`;
      }
    }
    return { d: path, total: n + margin * 2 };
  }, [value]);
  return (
    <svg viewBox={`0 0 ${total} ${total}`} width={size} height={size} role="img" aria-label={`QR code para ${value}`}
      shapeRendering="crispEdges" className="shrink-0 rounded-xl bg-white">
      <rect width={total} height={total} fill="#ffffff" />
      <path d={d} fill="#000000" />
    </svg>
  );
}
