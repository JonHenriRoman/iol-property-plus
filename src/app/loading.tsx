const Loading = () => {
  return (
    <div
      className="flex min-h-screen items-center justify-center"
      role="status"
      aria-label="Loading"
    >
      <span className="text-sm text-neutral-500">Loading…</span>
    </div>
  );
};

export default Loading;
