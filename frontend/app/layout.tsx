import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { TelegramApp } from "./telegram-app";
import "./style.css";

export const metadata: Metadata = { title: "Каталог", description: "Каталог товаров" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="afterInteractive" />
        <TelegramApp />
        {children}
      </body>
    </html>
  );
}
