import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const path = "outputs/019f71d9-85e1-7ff3-95e0-b8d51117763f/inventario_planilhas_padrao.xlsx";
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
console.log((await wb.inspect({kind:"table",sheetId:"Resumo",range:"A1:E10",include:"values,formulas",tableMaxRows:10,tableMaxCols:5,maxChars:3000})).ndjson);
const blob = await wb.render({sheetName:"Resumo",autoCrop:"all",scale:1,format:"png"});
await fs.writeFile("outputs/019f71d9-85e1-7ff3-95e0-b8d51117763f/resumo-preview.png",new Uint8Array(await blob.arrayBuffer()));
console.log("rendered");
