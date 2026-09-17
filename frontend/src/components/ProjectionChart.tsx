import { useRef, useState } from 'react';
import { dateShort, num } from '../format';
import type { ProjectionDay } from '../types';

const W = 1000;
const H = 340;
const PAD_L = 64;
const PAD_R = 24;
const PAD_T = 42;
const PAD_B = 46;

export function ProjectionChart({ daily, safetyStock = 0 }: { daily: ProjectionDay[]; safetyStock?: number }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const shortageIndexes = daily.map((day, index) => day.unmet > 0 ? index : -1).filter((index) => index >= 0);
  const firstShortageIndex = shortageIndexes[0] ?? null;
  const lastShortageIndex = shortageIndexes.at(-1) ?? null;
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (daily.length === 0) return null;

  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const maxVal = niceMax(Math.max(1, safetyStock, ...daily.map((day) => Math.max(day.opening, day.closing, day.receipts))));
  const xStep = plotW / Math.max(1, daily.length - 1);
  const xAt = (index: number) => PAD_L + index * xStep;
  const yAt = (value: number) => PAD_T + plotH - (value / maxVal) * plotH;
  const baseline = yAt(0);
  const inventoryPath = daily.map((day, index) => `${index === 0 ? 'M' : 'L'} ${xAt(index)} ${yAt(day.closing)}`).join(' ');
  const inventoryArea = `${inventoryPath} L ${xAt(daily.length - 1)} ${baseline} L ${xAt(0)} ${baseline} Z`;
  const selectedIndex = hoveredIndex ?? firstShortageIndex ?? 0;
  const selected = daily[selectedIndex];
  const totalUnmet = daily.reduce((total, day) => total + day.unmet, 0);
  const receiptDays = daily.filter((day) => day.receipts > 0);
  const yTicks = Array.from({ length: 5 }, (_, index) => Math.round((maxVal / 4) * index));
  const labelIndexes = new Set<number>([0, daily.length - 1]);
  for (let index = 0; index < daily.length; index += 4) labelIndexes.add(index);
  if (firstShortageIndex !== null) labelIndexes.add(firstShortageIndex);
  daily.forEach((day, index) => { if (day.receipts > 0) labelIndexes.add(index); });

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const viewX = (event.clientX - rect.left) * (W / rect.width);
    const index = Math.max(0, Math.min(daily.length - 1, Math.round((viewX - PAD_L) / xStep)));
    setHoveredIndex(index);
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950 p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-100">Projected closing inventory by day</h3>
          <p className="mt-1 text-xs text-gray-500">The blue area is sellable stock remaining after each day’s forecast demand.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <SummaryChip label="Unfilled demand" value={`${num(totalUnmet)} units`} tone={totalUnmet > 0 ? 'warn' : 'good'} />
          <SummaryChip label="Shortage days" value={`${shortageIndexes.length}`} tone={shortageIndexes.length > 0 ? 'warn' : 'good'} />
          <SummaryChip label="Confirmed receipts" value={`${receiptDays.length}`} />
        </div>
      </div>

      <div className="overflow-x-auto">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full min-w-[720px] touch-none"
          role="img"
          aria-label={`Inventory projection. ${totalUnmet} units of demand unfilled across ${shortageIndexes.length} days.`}
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHoveredIndex(null)}
        >
          <defs>
            <linearGradient id="inventory-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.34" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.03" />
            </linearGradient>
            <pattern id="shortage-pattern" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="8" height="8" fill="#450a0a" fillOpacity="0.5" />
              <line x1="0" y1="0" x2="0" y2="8" stroke="#ef4444" strokeOpacity="0.22" strokeWidth="3" />
            </pattern>
          </defs>

          {yTicks.map((tick) => <g key={tick}><line x1={PAD_L} x2={W - PAD_R} y1={yAt(tick)} y2={yAt(tick)} stroke="#252a35" /><text x={PAD_L - 10} y={yAt(tick) + 4} textAnchor="end" fontSize="11" fill="#7c8496">{num(tick)}</text></g>)}
          <text x={14} y={PAD_T - 16} fontSize="10" fill="#7c8496">UNITS</text>

          {firstShortageIndex !== null && lastShortageIndex !== null && (
            <g>
              <rect x={Math.max(PAD_L, xAt(firstShortageIndex) - xStep / 2)} y={PAD_T} width={Math.min(W - PAD_R, xAt(lastShortageIndex) + xStep / 2) - Math.max(PAD_L, xAt(firstShortageIndex) - xStep / 2)} height={plotH} fill="url(#shortage-pattern)" />
              <text x={(xAt(firstShortageIndex) + xAt(lastShortageIndex)) / 2} y={PAD_T + 18} textAnchor="middle" fontSize="11" fontWeight="600" fill="#fca5a5">SHORTAGE WINDOW · {num(totalUnmet)} UNITS UNFILLED</text>
            </g>
          )}

          {safetyStock > 0 && <g><line x1={PAD_L} x2={W - PAD_R} y1={yAt(safetyStock)} y2={yAt(safetyStock)} stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="6 5" /><text x={W - PAD_R - 4} y={yAt(safetyStock) - 7} textAnchor="end" fontSize="10" fill="#fbbf24">Safety stock {num(safetyStock)}</text></g>}

          <path d={inventoryArea} fill="url(#inventory-area)" />
          <path d={inventoryPath} fill="none" stroke="#38bdf8" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />

          {daily.map((day, index) => day.receipts > 0 ? (
            <g key={`receipt-${day.day}`}>
              <line x1={xAt(index)} x2={xAt(index)} y1={PAD_T} y2={baseline} stroke="#34d399" strokeWidth="2" strokeDasharray="4 4" />
              <polygon points={`${xAt(index)},${PAD_T - 5} ${xAt(index) - 6},${PAD_T + 6} ${xAt(index) + 6},${PAD_T + 6}`} fill="#34d399" />
              <text x={xAt(index) + 8} y={PAD_T + 12} fontSize="11" fontWeight="600" fill="#6ee7b7">+{num(day.receipts)} receipt</text>
            </g>
          ) : null)}

          <line x1={xAt(selectedIndex)} x2={xAt(selectedIndex)} y1={PAD_T} y2={baseline} stroke="#94a3b8" strokeWidth="1" strokeDasharray="3 4" opacity="0.8" />
          <circle cx={xAt(selectedIndex)} cy={yAt(selected.closing)} r="5" fill={selected.unmet > 0 ? '#ef4444' : '#38bdf8'} stroke="#e5e7eb" strokeWidth="2" />

          {daily.map((day, index) => labelIndexes.has(index) ? <text key={`label-${day.day}`} x={xAt(index)} y={H - PAD_B + 22} textAnchor={index === 0 ? 'start' : index === daily.length - 1 ? 'end' : 'middle'} fontSize="10" fill={index === selectedIndex ? '#e5e7eb' : '#7c8496'}>{dateShort(day.day)}</text> : null)}
          <line x1={PAD_L} x2={PAD_L} y1={PAD_T} y2={baseline} stroke="#3a3f4c" />
          <line x1={PAD_L} x2={W - PAD_R} y1={baseline} y2={baseline} stroke="#3a3f4c" />
        </svg>
      </div>

      <div className={`mt-3 rounded-lg border p-3 ${selected.unmet > 0 ? 'border-red-900/60 bg-red-950/15' : 'border-gray-800 bg-gray-900/50'}`} aria-live="polite">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-gray-100">{dateShort(selected.day)} {hoveredIndex === null && firstShortageIndex !== null ? '· first shortage day' : ''}</p>
          <p className={selected.unmet > 0 ? 'text-sm font-semibold text-red-300' : 'text-sm font-semibold text-emerald-300'}>{selected.unmet > 0 ? `${num(selected.unmet)} units unfilled` : 'Demand covered'}</p>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-x-5 gap-y-2 text-xs sm:grid-cols-5">
          <Detail label="Opening stock" value={num(selected.opening)} />
          <Detail label="Receipt" value={selected.receipts > 0 ? `+${num(selected.receipts)}` : '0'} />
          <Detail label="Forecast demand" value={`−${num(selected.demand)}`} />
          <Detail label="Demand served" value={num(selected.served)} />
          <Detail label="Closing stock" value={num(selected.closing)} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-gray-400">
        <Legend line color="#38bdf8" label="Closing inventory" />
        <Legend line dashed color="#f59e0b" label="Safety-stock target" />
        <Legend color="#ef4444" label="Shortage window" />
        <Legend line dashed color="#34d399" label="Confirmed receipt" />
        <span className="text-gray-600">Move across the chart to inspect any day.</span>
      </div>
    </div>
  );
}

function SummaryChip({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'warn' | 'good' }) {
  const color = tone === 'warn' ? 'border-red-900/70 text-red-300' : tone === 'good' ? 'border-emerald-900/70 text-emerald-300' : 'border-gray-700 text-gray-300';
  return <span className={`rounded-lg border bg-black/20 px-2.5 py-1.5 ${color}`}><span className="text-gray-500">{label}: </span><strong>{value}</strong></span>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><p className="text-gray-600">{label}</p><p className="mt-0.5 font-mono text-sm text-gray-200">{value}</p></div>;
}

function Legend({ color, label, line, dashed }: { color: string; label: string; line?: boolean; dashed?: boolean }) {
  return <span className="flex items-center gap-1.5">{line ? <svg width="18" height="10"><line x1="0" x2="18" y1="5" y2="5" stroke={color} strokeWidth="2.5" strokeDasharray={dashed ? '4 3' : undefined} /></svg> : <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />}{label}</span>;
}

function niceMax(value: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}
