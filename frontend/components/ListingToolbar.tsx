import HfIcon from './HfIcon';

export default function ListingToolbar({
  action,
  q,
  sort,
  placeholder,
}: {
  action: string;
  q?: string;
  sort?: string;
  placeholder: string;
}) {
  return (
    <form action={action} method="get" className="mb-6 flex flex-col gap-3 sm:flex-row">
      <div className="relative flex-1">
        <input
          type="text"
          name="q"
          defaultValue={q}
          placeholder={placeholder}
          className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 pl-10 text-sm text-zinc-900 placeholder-zinc-400 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-accent/30 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <span className="pointer-events-none absolute left-4 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center text-zinc-400">
          <HfIcon name="search" className="h-3.5 w-3.5" />
        </span>
      </div>

      <select
        name="sort"
        defaultValue={sort || 'updated'}
        className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm text-zinc-900 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-accent/30 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
      >
        <option value="updated">Trending</option>
        <option value="stars">Most liked</option>
      </select>

      <button
        type="submit"
        className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-semibold text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-950"
      >
        Search
      </button>
    </form>
  );
}
