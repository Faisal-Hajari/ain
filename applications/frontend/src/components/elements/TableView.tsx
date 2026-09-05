import type { TablePayload } from '@/api/types'

export function TableView({ data }: { data: TablePayload }) {
  return (
    <div className="-mx-1 flex-1 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            {data.columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-2 py-2 text-[11px] font-medium tracking-wide text-muted uppercase ${
                  column.align === 'end' ? 'text-end' : 'text-start'
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, index) => (
            <tr key={String(row[data.columns[0]!.key] ?? index)} className="border-b border-border/60 last:border-0">
              {data.columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-2 py-2 text-ink ${column.align === 'end' ? 'text-end tabular-nums' : 'text-start'}`}
                >
                  {row[column.key] ?? '-'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
