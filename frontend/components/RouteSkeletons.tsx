function LoadingStatus({ label }: { label: string }) {
  return <p className="sr-only" role="status" aria-live="polite">{label}</p>;
}

function Pulse({ className }: { className: string }) {
  return <span aria-hidden="true" className={`block animate-pulse rounded-lg bg-zinc-200/80 dark:bg-zinc-800 ${className}`} />;
}

export function CatalogSkeleton() {
  return (
    <section className="nyankoface-route-skeleton mx-auto w-full max-w-[1536px] px-4 py-8" aria-busy="true">
      <LoadingStatus label="一覧を読み込み中 · Loading catalog" />
      <div className="flex items-center gap-4">
        <Pulse className="h-9 w-52" />
        <Pulse className="h-8 w-28" />
      </div>
      <Pulse className="mt-6 h-11 w-full rounded-full" />
      <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => <Pulse key={index} className="h-[168px] rounded-xl" />)}
      </div>
    </section>
  );
}

export function KnowledgeListSkeleton() {
  return (
    <section className="nyankoface-route-skeleton mx-auto w-full max-w-[1536px] px-4 py-8" aria-busy="true">
      <LoadingStatus label="ナレッジ一覧を読み込み中 · Loading knowledge" />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Pulse className="h-10 w-72" />
        <Pulse className="h-9 w-44" />
      </div>
      <Pulse className="mt-6 h-12 w-full rounded-full" />
      <div className="mt-8 flex gap-7 overflow-hidden">
        {Array.from({ length: 7 }, (_, index) => <Pulse key={index} className="h-14 w-24 shrink-0" />)}
      </div>
      <Pulse className="mt-8 h-8 w-48" />
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => <Pulse key={index} className="h-[190px] rounded-xl" />)}
      </div>
    </section>
  );
}

export function KnowledgeArticleSkeleton() {
  return (
    <article className="nyankoface-route-skeleton min-h-screen" aria-busy="true">
      <LoadingStatus label="記事を読み込み中 · Loading article" />
      <div className="mx-auto flex max-w-[920px] justify-between px-5 py-4 sm:px-8">
        <Pulse className="h-7 w-28" />
        <Pulse className="h-8 w-32 rounded-full" />
      </div>
      <div className="border-y border-zinc-200 px-5 py-12 text-center dark:border-zinc-800 sm:py-16">
        <Pulse className="mx-auto h-28 w-28 rounded-[2rem] sm:h-36 sm:w-36" />
        <Pulse className="mx-auto mt-8 h-12 w-full max-w-[720px]" />
        <Pulse className="mx-auto mt-5 h-6 w-full max-w-xl" />
        <Pulse className="mx-auto mt-4 h-4 w-60" />
      </div>
      <div className="mx-auto grid max-w-[1040px] gap-10 px-5 py-10 sm:px-8 lg:grid-cols-[minmax(0,760px)_190px]">
        <div className="space-y-4">
          <Pulse className="h-8 w-2/3" />
          {Array.from({ length: 7 }, (_, index) => <Pulse key={index} className={`h-4 ${index % 3 === 2 ? 'w-4/5' : 'w-full'}`} />)}
          <Pulse className="mt-8 h-40 w-full" />
        </div>
        <Pulse className="h-40 w-full" />
      </div>
    </article>
  );
}

export function RepositorySkeleton() {
  return (
    <section className="nyankoface-route-skeleton mx-auto w-full max-w-[1536px] px-4 py-8" aria-busy="true">
      <LoadingStatus label="リポジトリ詳細を読み込み中 · Loading repository" />
      <div className="flex flex-wrap items-center gap-3">
        <Pulse className="h-8 w-24" />
        <Pulse className="h-10 w-72" />
      </div>
      <div className="mt-6 flex gap-3 border-b border-zinc-200 pb-3 dark:border-zinc-800">
        {Array.from({ length: 4 }, (_, index) => <Pulse key={index} className="h-10 w-28" />)}
      </div>
      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          <Pulse className="h-10 w-1/2" />
          {Array.from({ length: 8 }, (_, index) => <Pulse key={index} className={`h-4 ${index % 4 === 3 ? 'w-3/4' : 'w-full'}`} />)}
          <Pulse className="h-52 w-full" />
        </div>
        <div className="space-y-4">
          <Pulse className="h-28 w-full" />
          <Pulse className="h-44 w-full" />
        </div>
      </div>
    </section>
  );
}
