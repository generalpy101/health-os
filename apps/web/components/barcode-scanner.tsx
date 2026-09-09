"use client";

import { CameraOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface ScannerControls {
  stop: () => void;
}

/**
 * Camera barcode scanner (EAN/UPC/QR via @zxing/browser). The library is
 * imported lazily so it never ships in the initial bundle or runs during SSR.
 * If the camera is unavailable/denied, `onError` fires so the caller can fall
 * back to manual entry.
 */
export function BarcodeScanner({
  onResult,
  onError,
}: {
  onResult: (code: string) => void;
  onError?: (message: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let controls: ScannerControls | undefined;
    let cancelled = false;
    (async () => {
      try {
        const { BrowserMultiFormatReader } = await import("@zxing/browser");
        if (cancelled || !videoRef.current) return;
        const reader = new BrowserMultiFormatReader();
        controls = await reader.decodeFromVideoDevice(undefined, videoRef.current, (result, _err, ctrls) => {
          if (result && !cancelled) {
            cancelled = true;
            ctrls?.stop();
            onResultRef.current(result.getText());
          }
        });
      } catch {
        if (!cancelled) {
          setFailed(true);
          onError?.("Camera unavailable — type the barcode instead.");
        }
      }
    })();
    return () => {
      cancelled = true;
      controls?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (failed) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2.5 text-xs text-muted">
        <CameraOff size={14} className="shrink-0" /> Camera unavailable — type the barcode instead.
      </div>
    );
  }
  return (
    <video
      ref={videoRef}
      className="h-44 w-full rounded-xl border border-line bg-black object-cover"
      muted
      playsInline
      aria-label="Barcode camera preview"
    />
  );
}
