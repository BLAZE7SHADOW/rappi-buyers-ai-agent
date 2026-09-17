import { dateShort } from '../format';
import type { ProjectionDay } from '../types';

const W = 900;
const H = 280;
const PAD_L = 48;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 36;

export function ProjectionChart({ daily }: { daily: ProjectionDay[] }) {
  if (daily.length === 0) return null;

  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const n = daily.length;
  const maxVal = Math.max(1, ...daily.map((d) => Math.max(d.closing, d.demand, d.opening)));
  const xStep = plotW / Math.max(1, n - 1);

  const xAt = (i: number) => PAD_L + i * xStep;
  const yAt = (v: number) => PAD_T + plotH - (v / maxVal) * plotH;

  const closingPath = daily.map((d, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i)} ${yAt(d.closing)}`).join(' ');

  // y-axis ticks
  const tickCount = 4;
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => Math.round((maxVal / tickCount) * i));

  // x-axis: show every ~4th day label to avoid crowding
  const labelEvery = Math.max(1, Math.ceil(n / 9));

  const barW = Math.max(2, xStep * 0.7);

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]" role="img" aria-label="28-day inventory projection chart">
        {/* gridlines + y labels */}
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={yAt(t)} y2={yAt(t)} stroke="#262a36" strokeWidth={1} />
            <text x={PAD_L - 6} y={yAt(t) + 3} textAnchor="end" fontSize={10} fill="#8b90a0">
              {t}
            </text>
          </g>
        ))}

        {/* unmet-day shading */}
        {daily.map((d, i) =>
          d.unmet > 0 ? (
            <rect
              key={`shade-${d.day}`}
              x={xAt(i) - xStep / 2}
              y={PAD_T}
              width={xStep}
              height={plotH}
              fill="#7f1d1d"
              opacity={0.28}
            />
          ) : null,
        )}

        {/* demand bars (faint) */}
        {daily.map((d, i) => (
          <rect
            key={`demand-${d.day}`}
            x={xAt(i) - barW / 2}
            y={yAt(d.demand)}
            width={barW}
            height={Math.max(0, yAt(0) - yAt(d.demand))}
            fill="#38404f"
            opacity={0.5}
          />
        ))}

        {/* closing inventory line */}
        <path d={closingPath} fill="none" stroke="#38bdf8" strokeWidth={2.5} />

        {/* below-safety-stock markers */}
        {daily.map((d, i) =>
          d.below_safety ? (
            <circle key={`safety-${d.day}`} cx={xAt(i)} cy={yAt(d.closing)} r={2.5} fill="#f59e0b" />
          ) : null,
        )}

        {/* receipt markers */}
        {daily.map((d, i) =>
          d.receipts > 0 ? (
            <polygon
              key={`receipt-${d.day}`}
              points={`${xAt(i)},${PAD_T - 2} ${xAt(i) - 5},${PAD_T + 7} ${xAt(i) + 5},${PAD_T + 7}`}
              fill="#34d399"
            />
          ) : null,
        )}

        {/* x-axis labels */}
        {daily.map((d, i) =>
          i % labelEvery === 0 ? (
            <text key={`x-${d.day}`} x={xAt(i)} y={H - PAD_B + 16} textAnchor="middle" fontSize={10} fill="#8b90a0">
              {dateShort(d.day)}
            </text>
          ) : null,
        )}

        {/* axis lines */}
        <line x1={PAD_L} x2={PAD_L} y1={PAD_T} y2={H - PAD_B} stroke="#3a3f4c" strokeWidth={1} />
        <line x1={PAD_L} x2={W - PAD_R} y1={H - PAD_B} y2={H - PAD_B} stroke="#3a3f4c" strokeWidth={1} />
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-gray-400">
        <LegendItem color="#38bdf8" label="Closing inventory (line)" line />
        <LegendItem color="#38404f" label="Daily demand (bar)" />
        <LegendItem color="#7f1d1d" label="Unmet demand (shaded day)" opacity={0.5} />
        <span className="flex items-center gap-1.5">
          <svg width={10} height={10}>
            <polygon points="5,0 0,9 10,9" fill="#34d399" />
          </svg>
          Receipt day
        </span>
        <span className="flex items-center gap-1.5">
          <svg width={10} height={10}>
            <circle cx={5} cy={5} r={2.5} fill="#f59e0b" />
          </svg>
          Below safety stock
        </span>
      </div>
    </div>
  );
}

function LegendItem({ color, label, line, opacity }: { color: string; label: string; line?: boolean; opacity?: number }) {
  return (
    <span className="flex items-center gap-1.5">
      {line ? (
        <svg width={14} height={10}>
          <line x1={0} y1={5} x2={14} y2={5} stroke={color} strokeWidth={2.5} />
        </svg>
      ) : (
        <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color, opacity: opacity ?? 1 }} />
      )}
      {label}
    </span>
  );
}
