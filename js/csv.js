// CSV export. The payload never carries a BOM: Excel compatibility is created here, at
// the moment a human asks for a file, using the legacy header names recorded in the
// snapshot manifest so the export stays interchangeable with output/latest.csv.

const BOM = "\uFEFF";

export function toCsv(rows, columns, headerMap = {}) {
  const names = columns.length ? columns : Object.keys(rows[0] || {});
  const escape = (value) => {
    if (value === null || value === undefined) return "";
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [names.map((name) => escape(headerMap[name] || name)).join(",")];
  for (const row of rows) lines.push(names.map((name) => escape(row[name])).join(","));
  return BOM + lines.join("\r\n") + "\r\n";
}

export function download(filename, text, mime = "text/csv;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function stamp() {
  return new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
}
