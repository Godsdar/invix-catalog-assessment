import Link from "next/link";

export const dynamic = "force-dynamic";

type Product = { id: number; title: string; image_url: string };
type Catalog = { items: Product[]; next_cursor: number | null };

async function loadCatalog(after: number): Promise<Catalog | null> {
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8000"}/products?after=${after}`, {
      cache: "no-store", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return await response.json() as Catalog;
  } catch { return null; }
}

export default async function CatalogPage({ searchParams }: {
  searchParams: Promise<{ after?: string }>;
}) {
  const query = await searchParams;
  const number = Number(query.after ?? 0);
  const after = Number.isSafeInteger(number) && number >= 0 ? number : 0;
  const catalog = await loadCatalog(after);
  return (
    <main>
      <h1>Каталог</h1>
      {catalog === null ? (
        <div role="alert"><p>Не удалось загрузить товары. Попробуйте ещё раз.</p><a href="/">Повторить</a></div>
      ) : catalog.items.length === 0 ? (
        <p>{after ? "Больше товаров нет." : "Товаров пока нет."}</p>
      ) : (
        <ul className="products">
          {catalog.items.map(product => (
            <li key={product.id}>
              <h2>{product.title}</h2>
              {/* Original images are bounded and normalized by the server. */}
              <img src={product.image_url} alt={product.title} width={280} height={210} loading="lazy" />
            </li>
          ))}
        </ul>
      )}
      <nav aria-label="Страницы каталога">
        {after > 0 && <Link href="/">В начало</Link>}
        {catalog?.next_cursor !== null && catalog?.next_cursor !== undefined && (
          <Link href={`/?after=${catalog.next_cursor}`}>Следующие товары</Link>
        )}
      </nav>
    </main>
  );
}
