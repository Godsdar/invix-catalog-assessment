"use client";
import { useEffect } from "react";

type WebApp = { ready(): void; expand(): void };

export function TelegramApp() {
  useEffect(() => {
    const initialize = () => {
      const telegram = (window as Window & { Telegram?: { WebApp?: WebApp } }).Telegram;
      telegram?.WebApp?.ready();
      telegram?.WebApp?.expand();
      return Boolean(telegram?.WebApp);
    };
    if (initialize()) return;
    // The SDK loads asynchronously. A plain browser remains fully functional without it.
    const timer = window.setInterval(() => {
      if (initialize()) window.clearInterval(timer);
    }, 200);
    const stop = window.setTimeout(() => window.clearInterval(timer), 10_000);
    return () => { window.clearInterval(timer); window.clearTimeout(stop); };
  }, []);
  return null;
}
