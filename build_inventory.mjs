import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const data = JSON.parse(await fs.readFile("extracted_inventory.json", "utf8"));
const outDir = "outputs/019f71d9-85e1-7ff3-95e0-b8d51117763f";
await fs.mkdir(outDir, { recursive: true });
const wb = Workbook.create();

function addSheet(name, headers, rows, widths, applyColumnWidths=true) {
  const sh = wb.worksheets.add(name);
  const matrix = [headers, ...rows];
  const chunk = 5000;
  for (let i = 0; i < matrix.length; i += chunk) {
    const part = matrix.slice(i, i + chunk);
    sh.getRangeByIndexes(i, 0, part.length, headers.length).values = part;
  }
  sh.getRangeByIndexes(0, 0, 1, headers.length).format = {
    fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, wrapText: true,
    borders: { preset: "all", style: "thin", color: "#D9E2F3" }
  };
  sh.freezePanes.freezeRows(1);
  sh.showGridLines = false;
  if (applyColumnWidths) for (let c = 0; c < widths.length; c++) sh.getRangeByIndexes(0,c,Math.min(matrix.length,5000),1).format.columnWidth = widths[c];
  return sh;
}

const fileRows = data.arquivos.map((file) => {
  const cells = data.celulas.filter(c => c.arquivo === file);
  const fields = data.campos.filter(f => f.arquivo === file);
  const formulas = cells.filter(c => c.formula).length;
  return [file, new Set(cells.map(c=>c.aba)).size, fields.length, cells.length, formulas];
});
addSheet("Resumo", ["Arquivo","Abas","Campos identificados","Células preenchidas","Células com fórmula"], fileRows, [52,12,20,20,20]);

const fieldRows = data.campos.map(f => [f.arquivo,f.aba,f.coluna,f.nome_campo,f.linha_cabecalho,f.qtd_preenchidos,f.exemplos_valores,f.formulas,f.correspondencias]);
const fieldsSh = addSheet("Campos", ["Arquivo","Aba","Coluna","Nome do campo","Linha do cabeçalho","Qtd. preenchidos","Exemplos de valores","Fórmulas observadas","Correspondências em outros arquivos/abas"], fieldRows, [48,34,10,38,18,16,42,46,70]);
fieldsSh.getRange(`F2:F${fieldRows.length+1}`).format.numberFormat = "#,##0";

const cellRows = data.celulas.map(c => [c.arquivo,c.aba,c.celula,c.tipo,c.valor,c.formula,c.referencias_formula,c.contexto_linha]);
const cellsSh = addSheet("Celulas", ["Arquivo","Aba","Célula","Tipo","Valor exibido","Fórmula","Referências da fórmula","Contexto da linha"], cellRows, [48,34,10,12,28,52,52,90], false);

const formulaRows = data.celulas.filter(c => c.formula).map(c => [c.arquivo,c.aba,c.celula,c.formula,c.valor,c.referencias_formula]);
addSheet("Formulas", ["Arquivo","Aba","Célula","Fórmula","Valor exibido","Referências da fórmula"], formulaRows, [48,34,10,70,28,60], false);

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(`${outDir}/inventario_planilhas_padrao.xlsx`);
console.log(JSON.stringify({out:`${outDir}/inventario_planilhas_padrao.xlsx`,fields:fieldRows.length,cells:cellRows.length,formulas:formulaRows.length}));
