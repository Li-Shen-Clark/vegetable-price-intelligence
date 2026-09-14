import fs from "node:fs/promises";
import path from "node:path";
import { Workbook } from "@oai/artifact-tool";

const projectRoot = path.resolve(process.argv[2] ?? ".");
const inputPath = path.join(projectRoot, "reference/market_mapping.csv");
const outputPath = path.join(projectRoot, "reference/dim_city.csv");
const previewPath = "/private/tmp/veg-p0-artifact/dim_city_preview.png";

const sourceWorkbook = await Workbook.fromCSV(await fs.readFile(inputPath, "utf8"), {
  sheetName: "Market mapping",
});
const sourceValues = sourceWorkbook.worksheets
  .getItem("Market mapping")
  .getUsedRange(true).values;
const headers = sourceValues[0].map((value) => String(value));
const index = Object.fromEntries(headers.map((header, position) => [header, position]));
for (const required of ["market_id", "canonical_city", "canonical_province", "mapping_status"]) {
  if (!(required in index)) throw new Error(`Missing mapping column: ${required}`);
}

const byCity = new Map();
for (const row of sourceValues.slice(1)) {
  if (String(row[index.mapping_status]) !== "mapped_existing_city") continue;
  const city = String(row[index.canonical_city]);
  const province = String(row[index.canonical_province]);
  const marketId = String(row[index.market_id]);
  if (!city || !province || !marketId) throw new Error("Mapped city row has a blank identity field");
  if (!byCity.has(city)) byCity.set(city, { province, marketIds: [] });
  const item = byCity.get(city);
  if (item.province !== province) throw new Error(`City maps to multiple provinces: ${city}`);
  item.marketIds.push(marketId);
}

const cityNames = [...byCity.keys()].sort((left, right) => {
  const leftKey = `${byCity.get(left).province}\u0000${left}`;
  const rightKey = `${byCity.get(right).province}\u0000${right}`;
  return Buffer.compare(Buffer.from(leftKey, "utf8"), Buffer.from(rightKey, "utf8"));
});
if (cityNames.length !== 117) throw new Error(`Expected 117 cities, found ${cityNames.length}`);
const outputValues = [[
  "city_id",
  "city_name_zh",
  "province_name_zh",
  "included_market_count",
  "dimension_version",
]];
for (const [position, city] of cityNames.entries()) {
  const item = byCity.get(city);
  outputValues.push([
    `city_${String(position + 1).padStart(3, "0")}`,
    city,
    item.province,
    item.marketIds.length,
    "city_dim_v0.1",
  ]);
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Cities");
sheet.getRange("A1").write(outputValues);
workbook.recalculate();
const inspected = await workbook.inspect({
  kind: "table",
  range: "Cities!A1:E118",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 5,
  maxChars: 5000,
});
if (!inspected.ndjson.includes("city_001") || !inspected.ndjson.includes("city_dim_v0.1")) {
  throw new Error("Artifact inspection did not return expected city dimension values");
}
const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "city dimension formula error scan",
});
if (/"matchCount":\s*[1-9]/.test(errorScan.ndjson)) {
  throw new Error(`Unexpected spreadsheet error: ${errorScan.ndjson}`);
}
const preview = await workbook.render({
  sheetName: "Cities",
  range: "A1:E20",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

function serializeCell(value) {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
await fs.writeFile(
  outputPath,
  `${outputValues.map((row) => row.map(serializeCell).join(",")).join("\n")}\n`,
  "utf8",
);
const verifiedWorkbook = await Workbook.fromCSV(await fs.readFile(outputPath, "utf8"), {
  sheetName: "Cities",
});
const verifiedValues = verifiedWorkbook.worksheets.getItem("Cities").getUsedRange(true).values;
if (verifiedValues.length !== 118 || verifiedValues[0].length !== 5) {
  throw new Error(`CSV round-trip mismatch: ${verifiedValues.length} rows`);
}
console.log(JSON.stringify({
  outputPath,
  dataRows: outputValues.length - 1,
  columns: outputValues[0].length,
  totalMarkets: outputValues.slice(1).reduce((sum, row) => sum + Number(row[3]), 0),
  first: outputValues[1],
  last: outputValues.at(-1),
  previewPath,
}));
