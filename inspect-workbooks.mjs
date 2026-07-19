import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const files = process.argv.slice(2);
for (const path of files) {
  console.log(`FILE ${path}`);
  try {
    const input = await FileBlob.load(path);
    const wb = await SpreadsheetFile.importXlsx(input);
    console.log((await wb.inspect({kind:"workbook,sheet,table",maxChars:8000,tableMaxRows:8,tableMaxCols:10,tableMaxCellChars:120})).ndjson);
  } catch (e) {
    console.log(`ERROR ${e?.message || e}`);
  }
}
