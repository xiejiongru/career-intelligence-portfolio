// Hand-rolled SVG charts. Zero third-party JS is the point: no CDN, no supply chain, and
// every label is written with textContent, so job text can never become markup.

const SVG_NS = "http://www.w3.org/2000/svg";
const PALETTE = ["#2563a8", "#d97706", "#1f8a5a", "#a3367a", "#4b5563", "#8b6f00", "#3f6eb0"];

function el(name, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function shortLabel(label, max = 14) {
  const text = String(label);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function barChart(items, { title = "", height = 260, width = 520, horizontal = true } = {}) {
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart", role: "img" });
  if (title) svg.appendChild(el("text", { x: 8, y: 16, class: "chart-title" }, title));
  const data = items.filter(([, value]) => Number.isFinite(value) && value > 0);
  if (!data.length) {
    svg.appendChild(el("text", { x: 8, y: height / 2, class: "chart-empty" }, "无数据"));
    return svg;
  }
  const max = Math.max(...data.map(([, value]) => value));
  const top = 26;
  const plotHeight = height - top - 12;

  if (horizontal) {
    const rowH = Math.min(24, plotHeight / data.length);
    const labelW = 130;
    data.forEach(([label, value], index) => {
      const y = top + index * rowH;
      const barWidth = Math.max(1, ((width - labelW - 60) * value) / max);
      svg.appendChild(el("text", { x: labelW - 6, y: y + rowH * 0.7, class: "chart-label", "text-anchor": "end" }, shortLabel(label)));
      svg.appendChild(el("rect", { x: labelW, y: y + rowH * 0.18, width: barWidth, height: Math.max(6, rowH * 0.62), fill: PALETTE[0], rx: 2 }));
      svg.appendChild(el("text", { x: labelW + barWidth + 6, y: y + rowH * 0.7, class: "chart-value" }, String(value)));
    });
    return svg;
  }

  const colW = (width - 24) / data.length;
  data.forEach(([label, value], index) => {
    const barHeight = Math.max(1, ((plotHeight - 18) * value) / max);
    const x = 12 + index * colW;
    svg.appendChild(el("rect", { x: x + colW * 0.15, y: top + plotHeight - barHeight, width: colW * 0.7, height: barHeight, fill: PALETTE[0], rx: 2 }));
    svg.appendChild(el("text", { x: x + colW / 2, y: height - 6, class: "chart-label", "text-anchor": "middle" }, shortLabel(label, 10)));
    svg.appendChild(el("text", { x: x + colW / 2, y: top + plotHeight - barHeight - 4, class: "chart-value", "text-anchor": "middle" }, String(value)));
  });
  return svg;
}

export function histogram(values, { title = "", bins = 10, width = 520, height = 200 } = {}) {
  const clean = values.map(Number).filter((value) => Number.isFinite(value));
  if (!clean.length) {
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart", role: "img" });
    if (title) svg.appendChild(el("text", { x: 8, y: 16, class: "chart-title" }, title));
    svg.appendChild(el("text", { x: 8, y: height / 2, class: "chart-empty" }, "无可用数值"));
    return svg;
  }
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const edges = Array.from({ length: bins + 1 }, (_, i) => min + (span * i) / bins);
  const buckets = new Array(bins).fill(0);
  for (const value of clean) {
    let index = Math.floor(((value - min) / span) * bins);
    if (index >= bins) index = bins - 1;
    buckets[index] += 1;
  }
  return barChart(
    buckets.map((count, i) => [`${edges[i].toFixed(0)}–${edges[i + 1].toFixed(0)}`, count]),
    { title, width, height, horizontal: false }
  );
}

export function lineChart(series, { title = "", width = 640, height = 240, yLabel = "" } = {}) {
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart", role: "img" });
  if (title) svg.appendChild(el("text", { x: 8, y: 16, class: "chart-title" }, title));
  const points = series.flatMap((line) => line.points).filter(([, value]) => Number.isFinite(value));
  if (!points.length) {
    svg.appendChild(el("text", { x: 8, y: height / 2, class: "chart-empty" }, "无历史数据"));
    return svg;
  }
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys) || 1;
  const left = 44;
  const bottom = height - 28;
  const plotW = width - left - 16;
  const plotH = bottom - 30;
  const scaleX = (x) => left + (maxX === minX ? plotW / 2 : ((x - minX) / (maxX - minX)) * plotW);
  const scaleY = (y) => 30 + plotH - (y / maxY) * plotH;

  svg.appendChild(el("line", { x1: left, y1: bottom, x2: width - 16, y2: bottom, class: "axis" }));
  svg.appendChild(el("line", { x1: left, y1: 30, x2: left, y2: bottom, class: "axis" }));
  svg.appendChild(el("text", { x: 6, y: 34, class: "chart-label" }, String(maxY)));
  svg.appendChild(el("text", { x: 6, y: bottom, class: "chart-label" }, "0"));
  if (yLabel) svg.appendChild(el("text", { x: left + 4, y: 26, class: "chart-label" }, yLabel));

  series.forEach((line, index) => {
    const ordered = line.points.slice().sort((a, b) => a[0] - b[0]);
    const path = ordered.map(([x, y], i) => `${i ? "L" : "M"}${scaleX(x).toFixed(1)},${scaleY(y).toFixed(1)}`).join(" ");
    svg.appendChild(el("path", { d: path, fill: "none", stroke: PALETTE[index % PALETTE.length], "stroke-width": 2 }));
    for (const [x, y] of ordered) {
      svg.appendChild(el("circle", { cx: scaleX(x), cy: scaleY(y), r: 2.5, fill: PALETTE[index % PALETTE.length] }));
    }
  });

  const legendX = left;
  series.forEach((line, index) => {
    const y = height - 8;
    svg.appendChild(el("rect", { x: legendX + index * 140, y: y - 9, width: 10, height: 10, fill: PALETTE[index % PALETTE.length] }));
    svg.appendChild(el("text", { x: legendX + index * 140 + 14, y, class: "chart-label" }, line.name));
  });
  svg.appendChild(el("text", { x: left, y: height - 22, class: "chart-label" }, formatDay(minX)));
  svg.appendChild(el("text", { x: width - 16, y: height - 22, class: "chart-label", "text-anchor": "end" }, formatDay(maxX)));
  return svg;
}

function formatDay(ordinal) {
  const date = new Date(ordinal * 86400000);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
}

export function toOrdinal(dayText) {
  const date = new Date(`${String(dayText).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : Math.round(date.getTime() / 86400000);
}
