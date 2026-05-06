/**
 * Generic table renderer used by most report pages. Each column
 * declares its header label, alignment, and a render function that
 * receives the row object.
 *
 * Most reports are "summary tiles + one table" — this keeps each
 * page's markup down to the columns + tile values, not 30 lines of
 * `<table>` chrome.
 */

'use client';

import { cn } from '@/lib/utils';

export interface Column<Row> {
  key: string;
  label: string;
  align?: 'left' | 'right';
  className?: string;
  render: (row: Row) => React.ReactNode;
}

export interface ReportTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row, index: number) => string | number;
  emptyMessage?: string;
}

export function ReportTable<Row>({
  columns,
  rows,
  rowKey,
  emptyMessage = 'No rows in this window.',
}: ReportTableProps<Row>) {
  if (rows.length === 0) {
    return (
      <div className="border border-dashed rounded-lg bg-muted/20 px-6 py-10 text-center">
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      </div>
    );
  }
  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b bg-muted/20">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  'px-4 py-2 font-medium',
                  col.align === 'right' && 'text-right',
                )}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, i) => (
            <tr key={rowKey(row, i)} className="hover:bg-muted/30 transition-colors">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    'px-4 py-2 tabular-nums',
                    col.align === 'right' && 'text-right',
                    col.className,
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
