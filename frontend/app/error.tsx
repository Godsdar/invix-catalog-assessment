"use client";
export default function Error({ reset }: { reset(): void }) {
  return <main><h1>Каталог</h1><p role="alert">Не удалось открыть каталог.</p><button onClick={reset}>Повторить</button></main>;
}
