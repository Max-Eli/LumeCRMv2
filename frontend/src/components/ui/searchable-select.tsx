"use client"

import * as React from "react"
import { Combobox } from "@base-ui/react/combobox"
import { CheckIcon, ChevronsUpDownIcon, SearchIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * One selectable row. `meta` renders right-aligned + muted (e.g. a price
 * or a "12 services" count); it is display-only and never matched on.
 */
export interface SearchableSelectOption {
  value: string
  label: string
  meta?: React.ReactNode
}

/**
 * Type-ahead single-select built on Base UI's Combobox primitive.
 *
 * Use this instead of <Select> whenever the option list can grow long
 * (services, categories, providers, customers) — a tenant may have
 * dozens of services, and scrolling a plain dropdown is painful. The
 * popup is portalled + positioned by Base UI, so it never clips inside
 * grids, cards, or dialogs, and it ships keyboard nav + a11y for free.
 *
 * The public contract is a plain id string in / id string out, so it
 * drops into existing `value` / `onValueChange` call sites that already
 * speak in ids.
 */
export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  emptyText = "No matches.",
  disabled = false,
  ariaLabel,
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  options: SearchableSelectOption[]
  placeholder?: string
  emptyText?: string
  disabled?: boolean
  ariaLabel?: string
  className?: string
}) {
  // Resolve the controlled id to the option object Base UI tracks. Same
  // array reference as `items`, so equality + the check indicator work
  // without a custom `isItemEqualToValue`.
  const selected = React.useMemo(
    () => options.find((o) => o.value === value) ?? null,
    [options, value],
  )

  return (
    <Combobox.Root
      items={options}
      value={selected}
      disabled={disabled}
      onValueChange={(next) =>
        onValueChange((next as SearchableSelectOption | null)?.value ?? "")
      }
    >
      <div className={cn("relative", className)}>
        <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Combobox.Input
          placeholder={placeholder}
          aria-label={ariaLabel}
          className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent pr-8 pl-8 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30"
        />
        <Combobox.Trigger
          aria-label="Open"
          className="absolute right-1 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
        >
          <Combobox.Icon
            render={<ChevronsUpDownIcon className="size-3.5" />}
          />
        </Combobox.Trigger>
      </div>

      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="isolate z-50">
          <Combobox.Popup className="max-h-[min(var(--available-height),18rem)] w-[var(--anchor-width)] min-w-[12rem] origin-[var(--transform-origin)] overflow-y-auto overflow-x-hidden rounded-lg bg-popover py-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95">
            <Combobox.Empty className="px-3 py-3 text-center text-xs text-muted-foreground">
              {emptyText}
            </Combobox.Empty>
            <Combobox.List className="px-1">
              {(item: SearchableSelectOption) => (
                <Combobox.Item
                  key={item.value}
                  value={item}
                  className="relative flex w-full cursor-default items-center gap-3 rounded-md py-1.5 pr-8 pl-2 text-sm outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground data-disabled:pointer-events-none data-disabled:opacity-50"
                >
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.meta != null ? (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {item.meta}
                    </span>
                  ) : null}
                  <Combobox.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center">
                    <CheckIcon className="size-4" />
                  </Combobox.ItemIndicator>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  )
}
