import type { ReactNode } from 'react';

/**
 * A plain data table shell. Wraps in a horizontally scrollable container so wide
 * tables never push the page body sideways.
 */
const Table = ({ head, children }: { head: ReactNode; children: ReactNode }) => {
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-surface text-left text-xs font-semibold text-ink-muted uppercase">
          {head}
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
};

const Th = ({ children }: { children?: ReactNode }) => (
  <th className="border-b border-line px-3 py-2 font-semibold">{children}</th>
);

const Td = ({ children }: { children?: ReactNode }) => (
  <td className="border-b border-line px-3 py-2 align-top">{children}</td>
);

export default Table;
export { Td, Th };
