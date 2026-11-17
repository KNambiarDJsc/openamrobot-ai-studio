"use client";
import { useMemo, useState } from "react";

export type Series = { key: string; label: string; color: string; points: (number | null)[]; times?: string[] };

type Props = { title: string; unit: string; series: Series[]; height?: number; emptyText: string; caption?: string };

const W = 640;
const PAD = { l: 52, r: 92, t: 12, b: 26 };

function niceTicks(min: number, max: number, n = 4): number[] {
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const raw = (max - min) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/**
 * One y-axis, thin 2px lines, a legend for >= 2 series plus end-of-line direct labels, a crosshair and
 * tooltip on hover, recessive grid. Gaps (null) are drawn as breaks, never interpolated.
 */
export function LineChart({ title, unit, series, height = 200, emptyText, caption }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const n = Math.max(0, ...series.map((s) => s.points.length));
  const values = series.flatMap((s) => s.points.filter((v): v is number => v !== null));

  const geom = useMemo(() => {
    if (!values.length || n < 2) return null;
    const ticks = niceTicks(Math.min(...values), Math.max(...values));
    const y0 = ticks[0];
    const y1 = ticks[ticks.length - 1];
    const x = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const y = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0 || 1)) * (height - PAD.t - PAD.b);
    const paths = series.map((s) => {
      let d = "";
      let pen = false;
      s.points.forEach((v, i) => {
        if (v === null) {
          pen = false;
          return;
        }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    });
    return { ticks, x, y, paths };
  }, [series, values.length, n, height]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!geom) {
    return (
      <figure className="chart">
        <figcaption className="chart-title">{title}</figcaption>
        <div className="chart-empty" style={{ height }}>{emptyText}</div>
      </figure>
    );
  }
  const { ticks, x, y, paths } = geom;
  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    if (!Number.isFinite(e.clientX) || !r.width) return;
    const px = ((e.clientX - r.left) / r.width) * (W - PAD.l - PAD.r);
    setHover(Math.max(0, Math.min(n - 1, Math.round((px / (W - PAD.l - PAD.r)) * (n - 1)))));
  };
  const lastIdx = (s: Series) => {
    for (let i = s.points.length - 1; i >= 0; i--) if (s.points[i] !== null) return i;
    return -1;
  };

  return (
    <figure className="chart">
      <figcaption className="chart-title">
        {title} <span className="chart-unit">({unit})</span>
      </figcaption>
      {series.length >= 2 && (
        <ul className="legend">
          {series.map((s) => (
            <li key={s.key}><span className="legend-swatch" style={{ background: s.color }} />{s.label}</li>
          ))}
        </ul>
      )}
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${title} in ${unit}`} className="chart-svg">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid" />
              <text x={PAD.l - 8} y={y(t)} className="tick" textAnchor="end" dominantBaseline="middle">{t}</text>
            </g>
          ))}
          {paths.map((d, i) => (
            <path key={series[i].key} d={d} fill="none" stroke={series[i].color} strokeWidth={2}
              strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {series.map((s) => {
            const i = lastIdx(s);
            if (i < 0) return null;
            return (
              <text key={s.key} x={x(i) + 8} y={y(s.points[i] as number)} className="direct-label"
                dominantBaseline="middle">{s.label}</text>
            );
          })}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={height - PAD.b} className="crosshair" />
              {series.map((s) => s.points[hover] !== null && s.points[hover] !== undefined ? (
                <circle key={s.key} cx={x(hover)} cy={y(s.points[hover] as number)} r={4} fill={s.color}
                  stroke="var(--surface-2)" strokeWidth={2} />
              ) : null)}
            </g>
          )}
          <text x={PAD.l} y={height - 6} className="tick">oldest</text>
          <text x={W - PAD.r} y={height - 6} className="tick" textAnchor="end">latest</text>
          <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={height - PAD.t - PAD.b} fill="transparent"
            onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
        {hover !== null && (
          <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%` }} role="status">
            <div className="tooltip-time">{series[0]?.times?.[hover] ?? `frame ${hover + 1}/${n}`}</div>
            {series.map((s) => (
              <div key={s.key} className="tooltip-row">
                <span className="legend-swatch" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="mono">{s.points[hover] === null || s.points[hover] === undefined ? "—"
                  : `${(s.points[hover] as number).toFixed(4)} ${unit}`}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {caption && <p className="chart-caption">{caption}</p>}
    </figure>
  );
}
