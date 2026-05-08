import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from collections import OrderedDict
import re
import unicodedata

# =========================================================
# GERADOR XML V21
# - V21: replica o preenchimento humano da PlanilhaPadrao.
# - 1 linha válida da CALIA = 1 <veiculacao>. Não agrupa.
# - DataInicio/DataFim vêm do período global da aba: primeira e última inserção no grid da aba.
# - QuantidadeDeInsercoes continua vindo da coluna INS quando existir; senão, soma o grid da linha.
# - Horário vazio em TV vira 00:00 a 00:00.
# =========================================================

MESES = {
    "JANEIRO": 1, "JAN": 1,
    "FEVEREIRO": 2, "FEV": 2,
    "MARÇO": 3, "MARCO": 3, "MAR": 3,
    "ABRIL": 4, "ABR": 4,
    "MAIO": 5, "MAI": 5,
    "JUNHO": 6, "JUN": 6,
    "JULHO": 7, "JUL": 7,
    "AGOSTO": 8, "AGO": 8,
    "SETEMBRO": 9, "SET": 9,
    "OUTUBRO": 10, "OUT": 10,
    "NOVEMBRO": 11, "NOV": 11,
    "DEZEMBRO": 12, "DEZ": 12,
}

XML_EMPTY_VALUE = ""

# -------------------------
# Texto / normalização
# -------------------------

def limpar_texto_agressivo(texto):
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    texto_str = str(texto).strip()
    if texto_str.lower() in ["nan", "none"]:
        return ""

    substituicoes = {
        "\xa0": " ", "–": "-", "—": "-", "“": '"', "”": '"',
        "‘": "'", "’": "'", "…": "..."
    }
    for original, novo in substituicoes.items():
        texto_str = texto_str.replace(original, novo)

    texto_norm = unicodedata.normalize("NFC", texto_str)
    return "".join(
        ch for ch in texto_norm
        if unicodedata.category(ch)[0] != "C" or ch in ["\n", "\t", "\r"]
    )


def texto_upper(valor):
    return limpar_texto_agressivo(valor).upper().strip()


def texto_celula(row, idx, default=""):
    if idx is None:
        return default
    try:
        return limpar_texto_agressivo(row[idx])
    except Exception:
        return default


def eh_vazio(valor):
    if valor is None:
        return True
    if isinstance(valor, float) and pd.isna(valor):
        return True
    return str(valor).strip().lower() in ["", "nan", "none", "-", "0", "0.0"]


def eh_linha_descartavel(row):
    texto = " ".join(texto_upper(x) for x in row if not eh_vazio(x))
    if not texto:
        return True
    termos_bloqueio = [
        "TOTAL", "SUBTOTAL", "OBSERVA", "OBS.", "INVESTIMENTO",
        "RESUMO", "PRAÇA", "PRACA", "FORMATO COMERCIAL"
    ]
    # Não descarta qualquer linha que contenha praça, apenas linhas que comecem/pareçam cabeçalho.
    if texto.startswith(("TOTAL", "SUBTOTAL", "OBS", "INVESTIMENTO", "RESUMO")):
        return True
    return False

# -------------------------
# Conversões
# -------------------------

def numero_float(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()
    if s.lower() in ["", "nan", "none", "-"]:
        return None
    s = s.replace("R$", "").replace("%", "").replace(" ", "")

    # BR: 1.234,56 -> 1234.56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


def formatar_valor_br(valor, eh_porcentagem=False, vazio_se_invalido=False):
    val_float = numero_float(valor)
    if val_float is None:
        return "" if vazio_se_invalido else "0,00000000000000"

    if eh_porcentagem and 0 < val_float <= 1:
        val_float *= 100

    val_float = round(val_float, 2)
    return f"{val_float:.14f}".replace(".", ",")


def formatar_horario(valor):
    if eh_vazio(valor):
        return ""
    if hasattr(valor, "strftime"):
        return valor.strftime("%H:%M")
    if isinstance(valor, (float, int)):
        # Excel guarda hora como fração do dia.
        if 0 <= float(valor) < 1:
            segundos = int(round(float(valor) * 24 * 3600))
            segundos = segundos % (24 * 3600)
            return (datetime(1900, 1, 1) + timedelta(seconds=segundos)).strftime("%H:%M")

    s = str(valor).strip()
    match = re.search(r"(\d{1,2})[:hH](\d{2})", s)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        return f"{h:02d}:{m:02d}"
    return ""


def formatar_data_obj(dt):
    return dt.strftime("%d/%m/%Y")


def normalizar_id(valor):
    val = numero_float(valor)
    if val is None:
        return ""
    try:
        return str(int(val))
    except Exception:
        return ""


def normalizar_codigo_territorio(valor):
    if eh_vazio(valor):
        return ""
    s = limpar_texto_agressivo(valor).strip().upper().replace(".0", "")
    if re.fullmatch(r"[A-Z]{2,3}", s):
        return s
    return re.sub(r"\D", "", s)


def campos_territorio_xml(codigo_territorio):
    codigo = normalizar_codigo_territorio(codigo_territorio)
    if re.fullmatch(r"[A-Z]{3}", codigo):
        return codigo, "", ""
    if re.fullmatch(r"[A-Z]{2}", codigo):
        return "", codigo, ""
    if codigo:
        return "", "", codigo
    return "BRA", "", ""

# -------------------------
# Cabeçalhos / mapeamento
# -------------------------

def encontrar_inicio_triplo(df):
    for i in range(len(df) - 2):
        l1 = " ".join(texto_upper(x) for x in df.iloc[i].values if not eh_vazio(x))
        tem_id = "ID SECOM" in l1 or "ID. SECOM" in l1
        tem_campo_chave = any(t in l1 for t in ["PROGRAMA", "REDE", "VEÍCULO", "VEICULO", "NOME FANTASIA", "EMISSORA"])
        if tem_id and tem_campo_chave:
            return i
    return None


def carregar_linhas_cabecalho(df, linha_inicio):
    row1 = df.iloc[linha_inicio].fillna("").astype(str).map(texto_upper).tolist()
    row2 = df.iloc[linha_inicio + 1].fillna("").astype(str).map(texto_upper).tolist()
    row3 = df.iloc[linha_inicio + 2].fillna("").astype(str).map(texto_upper).tolist()
    return row1, row2, row3


def detectar_mes(texto):
    t = texto_upper(texto)
    for nome_mes, mes in MESES.items():
        if nome_mes in t:
            return mes
    return None


def mapear_colunas_triplas(df, linha_inicio, ano_campanha):
    row1, row2, row3 = carregar_linhas_cabecalho(df, linha_inicio)
    mapa = {"DIAS": [], "CANDIDATOS_NOME": [], "VALOR_TABELA_FORMATOS": {}}

    last_r1 = ""
    mes_atual = None
    ano_atual = ano_campanha

    for idx in range(len(row1)):
        r1 = row1[idx] or last_r1
        if row1[idx]:
            last_r1 = row1[idx]
        r2 = row2[idx]
        r3 = row3[idx]
        combinado = f"{r1} {r2} {r3}".strip()
        combinado_direto = f"{row1[idx]} {r2} {r3}".strip()

        mes_detectado = detectar_mes(r1) or detectar_mes(r2)
        if mes_detectado:
            mes_atual = mes_detectado
            # Em campanhas que cruzam dez/jan, janeiro pertence ao ano seguinte.
            ano_atual = ano_campanha + 1 if mes_atual == 1 and ano_campanha and mes_atual < 3 else ano_campanha

        if "ID SECOM" in combinado_direto or "ID. SECOM" in combinado_direto:
            mapa["ID_VEICULO"] = idx

        # Nome: guarda candidatos em ordem de qualidade; no fim escolhe o melhor.
        if any(t in combinado_direto for t in ["NOME FANTASIA", "EMISSORA", "VEÍCULO", "VEICULO", "REDE"]):
            score = 0
            if "NOME FANTASIA" in combinado_direto: score += 5
            if "EMISSORA" in combinado_direto: score += 4
            if "VEÍCULO" in combinado_direto or "VEICULO" in combinado_direto: score += 3
            if "REDE" in combinado_direto: score += 2
            if "ID" in combinado_direto: score -= 4
            if "TOTAL" in combinado_direto or "VALOR" in combinado_direto: score -= 3
            mapa["CANDIDATOS_NOME"].append((score, idx, combinado_direto))

        if "PROGRAMA" in combinado_direto and "HORÁRIO" not in combinado_direto and "HORARIO" not in combinado_direto:
            mapa["PROGRAMA"] = idx

        if "FORMATO" in combinado_direto or "PEÇA" in combinado_direto or "PECA" in combinado_direto:
            if "VALOR" not in combinado_direto and "CUSTO" not in combinado_direto:
                mapa["FORMATO"] = idx

        if any(t in combinado_direto for t in ["SECUNDAGEM", "DURAÇÃO", "DURACAO"]):
            mapa["SECUNDAGEM"] = idx

        # Inserções totais.
        termos_ins = ["TT. INS", "TT.INS", "TT INS", "TOTAL INSERÇÕES", "TOTAL INSERCOES", "QTD.", "QUANTIDADE"]
        eh_coluna_ins = any(t in combinado_direto for t in termos_ins)
        eh_ins_isolado = bool(re.search(r"(^|\s)INS\.?($|\s)", combinado_direto))
        nao_eh_valor = "VALOR" not in combinado_direto and "CUSTO" not in combinado_direto and "TABELA" not in combinado_direto
        if (eh_coluna_ins or eh_ins_isolado) and nao_eh_valor:
            mapa["INSERCOES"] = idx

        # Desconto: prioriza colunas percentuais.
        # IMPORTANTE: não usar "VALOR NEGOCIADO" como desconto; isso é valor em R$.
        tem_desc = any(t in combinado_direto for t in ["DESC", "DESCONTO", "% NEG", "%NEG", "PERCENTUAL NEG"])
        tem_pup = "PUP" in combinado_direto
        tem_reapl = "REAPL" in combinado_direto or "REAPLIC" in combinado_direto
        eh_valor_monetario = "VALOR" in combinado_direto or "CUSTO" in combinado_direto or "R$" in combinado_direto
        if tem_desc and not tem_reapl and not eh_valor_monetario and "DESCONTO" not in mapa:
            mapa["DESCONTO"] = idx
        elif tem_pup and not tem_reapl and not eh_valor_monetario and "DESCONTO" not in mapa:
            mapa["DESCONTO"] = idx

        # Horários.
        if any(t in r1 for t in ["HORÁRIO", "HORARIO", "FAIXA HORÁRIA", "FAIXA HORARIA", "FAIXA"]):
            if any(t in r2 for t in ["INICIAL", "INÍCIO", "INICIO"]):
                mapa["HORA_INI"] = idx
            if any(t in r2 for t in ["FINAL", "FIM", "TÉRMINO", "TERMINO"]):
                mapa["HORA_FIM"] = idx

        # Valor de tabela unitário.
        # IMPORTANTE: não sobrescrever com VALOR NEGOCIADO / DESEMBOLSO.
        eh_valor_tabela = "TABELA" in combinado and ("VALOR" in combinado or "CUSTO" in combinado)
        eh_unitario = any(t in combinado for t in ["UNITÁRIO", "UNITARIO", "UNIT"])
        if eh_valor_tabela and eh_unitario:
            mapa["VALOR_TABELA"] = idx
            formato_unitario = re.search(r"\b(5|10|15|30|60|90)\b", combinado)
            if formato_unitario:
                mapa["VALOR_TABELA_FORMATOS"][formato_unitario.group(1)] = idx
        elif eh_valor_tabela and "VALOR_TABELA" not in mapa:
            mapa["VALOR_TABELA"] = idx

        # Município / IBGE.
        if any(t in combinado_direto for t in ["CÓD", "COD", "IBGE"]) and any(t in combinado_direto for t in ["MUN", "MÚN", "MUNIC"]):
            mapa["COD_MUNICIPIO"] = idx

        # Grid de dias. Normalmente o dia está na terceira linha do cabeçalho.
        dia_txt = r3.strip()
        if re.fullmatch(r"\d{1,2}", dia_txt) and mes_atual:
            dia = int(dia_txt)
            if 1 <= dia <= 31:
                mapa["DIAS"].append({"idx": idx, "dia": dia, "mes": mes_atual, "ano": ano_atual})

    if mapa["CANDIDATOS_NOME"]:
        mapa["CANDIDATOS_NOME"].sort(reverse=True)
        mapa["NOME"] = mapa["CANDIDATOS_NOME"][0][1]

    return mapa

# -------------------------
# Datas / inserções
# -------------------------

def ler_datas_grid(row, lista_dias):
    datas_validas = []
    total_insercoes_grid = 0

    for info in lista_dias:
        col_idx = info["idx"]
        try:
            val = row[col_idx]
        except Exception:
            continue

        if eh_vazio(val):
            continue

        n = numero_float(val)
        if n is None:
            # Qualquer marca textual não vazia conta como 1 inserção.
            qtd = 1
        else:
            qtd = int(round(n)) if n > 0 else 0

        if qtd > 0:
            datas_validas.append(datetime(info["ano"], info["mes"], info["dia"]))
            total_insercoes_grid += qtd

    datas_validas.sort()
    return datas_validas, total_insercoes_grid


def obter_insercoes(row, mapa, total_grid):
    # Preferência: coluna total INS, quando confiável.
    if "INSERCOES" in mapa:
        n = numero_float(row[mapa["INSERCOES"]])
        if n is not None and n > 0:
            return int(round(n))
    return int(total_grid or 0)

# -------------------------
# Normalização de uma linha
# -------------------------

def detectar_tipo_midia(nome_aba, df):
    nome_upper = texto_upper(nome_aba)
    sample = ""
    try:
        sample = df.head(20).astype(str).to_string().upper()
    except Exception:
        pass

    if "PROGRAMAÇÃO - RÁDIO" in sample or "PROGRAMAÇÃO - RADIO" in sample:
        return "RADIO"
    if "PROGRAMAÇÃO - TELEVISÃO" in sample or "PROGRAMAÇÃO - TV" in sample:
        return "TV"

    if any(t in nome_upper for t in ["RADIO", "RÁDIO", " RD ", "RD "]):
        return "RADIO"
    if any(t in nome_upper for t in ["TV", "TELEVISÃO", "TELEVISAO", "CNN", "REDE VIDA"]):
        return "TV"
    return None


def detectar_periodo_global_aba(df, linha_inicio, mapa):
    """
    Regra V21: DataInicio/DataFim são por aba, não por linha.
    O período global da aba é a primeira e a última data que possuem qualquer inserção
    em linhas válidas daquela aba.
    """
    todas_datas = []
    for row_idx in range(linha_inicio + 3, len(df)):
        row = df.iloc[row_idx].values
        if "ID_VEICULO" not in mapa or eh_linha_descartavel(row):
            continue
        id_veiculo = normalizar_id(row[mapa["ID_VEICULO"]])
        if not id_veiculo:
            continue
        datas_linha, total_grid = ler_datas_grid(row, mapa.get("DIAS", []))
        insercoes = obter_insercoes(row, mapa, total_grid)
        if insercoes <= 0:
            continue
        todas_datas.extend(datas_linha)
    todas_datas = sorted([d for d in todas_datas if isinstance(d, datetime)])
    if not todas_datas:
        return []
    return [todas_datas[0], todas_datas[-1]]


def normalizar_formato(valor, tipo_midia):
    formato = "30" if tipo_midia == "TV" else ""
    val_fmt = limpar_texto_agressivo(valor).replace('"', "").strip().upper()
    if not val_fmt:
        return formato

    fmt_num = numero_float(val_fmt)
    if fmt_num is not None and fmt_num > 0:
        return str(int(fmt_num))

    fmt_match = re.search(r"\d+", val_fmt)
    if fmt_match:
        return str(int(fmt_match.group(0)))

    # Exemplos comuns: PEÇA A, PECA A, A, 30S, 15''.
    if tipo_midia == "TV":
        if re.search(r"(^|\s)A($|\s)", val_fmt) or "30" in val_fmt:
            return "30"
        if re.search(r"(^|\s)B($|\s)", val_fmt) or "15" in val_fmt:
            return "15"
    return val_fmt


def obter_formato_tv(row, mapa, nome_aba=""):
    if "SECUNDAGEM" in mapa:
        formato_seg = normalizar_formato(row[mapa["SECUNDAGEM"]], "TV")
        if formato_seg:
            return formato_seg

    formato = "30"
    if "FORMATO" in mapa:
        formato = normalizar_formato(row[mapa["FORMATO"]], "TV")

    if formato == "15":
        nome_aba_upper = texto_upper(nome_aba)
        if any(t in nome_aba_upper for t in ["PROJETO", "FECHADA"]):
            return "60"
        return "30"

    return formato


def obter_valor_tabela(row, mapa, formato):
    formatos = mapa.get("VALOR_TABELA_FORMATOS", {})
    if formato in formatos:
        return formatar_valor_br(row[formatos[formato]])
    if "VALOR_TABELA" in mapa:
        return formatar_valor_br(row[mapa["VALOR_TABELA"]])
    return "0,00000000000000"


def extrair_registro(tipo_midia, row, mapa, periodo_global=None, nome_aba=""):
    if "ID_VEICULO" not in mapa:
        return None
    if eh_linha_descartavel(row):
        return None

    id_veiculo = normalizar_id(row[mapa["ID_VEICULO"]])
    if not id_veiculo:
        return None

    datas_linha, total_grid = ler_datas_grid(row, mapa.get("DIAS", []))
    insercoes = obter_insercoes(row, mapa, total_grid)
    if insercoes <= 0:
        return None

    nome = texto_celula(row, mapa.get("NOME"), "")
    programa = texto_celula(row, mapa.get("PROGRAMA"), "ROTATIVO") or "ROTATIVO"
    if texto_upper(programa).startswith(("TOTAL", "SUBTOTAL", "OBS")):
        return None

    hora_ini = formatar_horario(row[mapa["HORA_INI"]]) if "HORA_INI" in mapa else ""
    hora_fim = formatar_horario(row[mapa["HORA_FIM"]]) if "HORA_FIM" in mapa else ""
    if not hora_fim and "HORA_INI" in mapa:
        try:
            hora_fim = formatar_horario(row[mapa["HORA_INI"] + 1])
        except Exception:
            pass

    # Regra confirmada: em TV, horário vazio vira 00:00 a 00:00.
    if tipo_midia == "TV" and not hora_ini:
        hora_ini = "00:00"
    if tipo_midia == "TV" and not hora_fim:
        hora_fim = "00:00"

    # Rádio mantém fallback antigo, quando não houver horário inicial.
    if not hora_ini and tipo_midia == "RADIO":
        hora_ini = "06:00"
    if not hora_fim:
        hora_fim = hora_ini

    desconto = formatar_valor_br(row[mapa["DESCONTO"]], eh_porcentagem=True, vazio_se_invalido=True) if "DESCONTO" in mapa else ""
    if not desconto:
        desconto = "0,00000000000000"

    if tipo_midia == "TV":
        formato = obter_formato_tv(row, mapa, nome_aba=nome_aba)
    else:
        formato = ""
        if "FORMATO" in mapa:
            formato = normalizar_formato(row[mapa["FORMATO"]], tipo_midia)

    if tipo_midia == "RADIO" and texto_upper(formato) in ["ONLINE", "A DEFINIR"]:
        return None

    valor_tabela = obter_valor_tabela(row, mapa, formato)

    cod_municipio = normalizar_codigo_territorio(row[mapa["COD_MUNICIPIO"]]) if "COD_MUNICIPIO" in mapa else ""

    # Datas finais do XML: período global da aba. Fallback para linha se a aba não tiver grid detectado.
    datas_xml = list(periodo_global or []) or datas_linha

    return {
        "tipo_midia": tipo_midia,
        "id_veiculo": id_veiculo,
        "nome": nome,
        "datas": datas_xml,
        "programa": programa,
        "hora_ini": hora_ini,
        "hora_fim": hora_fim,
        "desconto": desconto,
        "insercoes": insercoes,
        "formato": formato,
        "valor_tabela": valor_tabela,
        "cod_municipio": cod_municipio,
        "tipo_compra": "TESTEMUNHAL" if tipo_midia == "RADIO" and "TEST" in texto_upper(nome_aba) else "DETERMINADO",
    }

# -------------------------
# Agrupamento
# -------------------------

def chave_agrupamento(reg):
    # Mantém campos que impactam valor/regras; soma apenas registros equivalentes.
    return (
        reg["tipo_midia"], reg["id_veiculo"], reg["nome"], reg["programa"],
        reg["hora_ini"], reg["hora_fim"], reg["desconto"], reg["formato"],
        reg["valor_tabela"], reg["cod_municipio"]
    )


def agrupar_registros(registros):
    grupos = OrderedDict()
    for reg in registros:
        key = chave_agrupamento(reg)
        if key not in grupos:
            grupos[key] = dict(reg)
            grupos[key]["datas"] = list(reg.get("datas", []))
        else:
            grupos[key]["insercoes"] += reg.get("insercoes", 0)
            grupos[key]["datas"].extend(reg.get("datas", []))
    return list(grupos.values())

# -------------------------
# XML
# -------------------------

def criar_tag(pai, nome, valor):
    elem = ET.SubElement(pai, nome)
    elem.text = limpar_texto_agressivo(valor)


def datas_inicio_fim(datas):
    datas = sorted([d for d in datas if isinstance(d, datetime)])
    if not datas:
        return "", ""
    return formatar_data_obj(datas[0]), formatar_data_obj(datas[-1])


def gerar_conteudo_xml(tipo_midia, registros, agrupar=True):
    if agrupar:
        registros = agrupar_registros(registros)

    root = ET.Element("documento")
    id_counter = 1

    for reg in registros:
        veiculacao = ET.SubElement(root, "veiculacao", id=str(id_counter))
        data_ini, data_fim = datas_inicio_fim(reg.get("datas", []))

        criar_tag(veiculacao, "IdentificadorVeiculacaoSistemaOrigem", id_counter)
        criar_tag(veiculacao, "TipoInformacao", "Planejado")
        criar_tag(veiculacao, "IdentificadorVeiculacao", "")
        criar_tag(veiculacao, "IdentificadorVeiculo", reg["id_veiculo"])

        if tipo_midia == "RADIO":
            criar_tag(veiculacao, "IdNegociacao", "")

        criar_tag(veiculacao, "Nome", reg.get("nome", ""))
        criar_tag(veiculacao, "DataInicioDaVeiculacao", data_ini)
        criar_tag(veiculacao, "DataFimDaVeiculacao", data_fim)
        criar_tag(veiculacao, "Programa", "ROTATIVO" if tipo_midia == "RADIO" else reg.get("programa", "ROTATIVO"))
        criar_tag(veiculacao, "FaixaHorariaInicial", reg.get("hora_ini", ""))
        criar_tag(veiculacao, "FaixaHorariaFinal", reg.get("hora_fim", ""))

        if tipo_midia == "TV":
            criar_tag(veiculacao, "Bonificacao", "nao")
            criar_tag(veiculacao, "DescontoNegociado", reg.get("desconto", "0,00000000000000"))
            criar_tag(veiculacao, "QuantidadeDeInsercoes", reg.get("insercoes", 0))
            criar_tag(veiculacao, "FormatoTV", reg.get("formato", "30"))
            criar_tag(veiculacao, "CustoDeTabelaFormato", reg.get("valor_tabela", "0,00000000000000"))
        elif tipo_midia == "RADIO":
            criar_tag(veiculacao, "Formato", reg.get("formato", ""))
            criar_tag(veiculacao, "CustoDoFormato", reg.get("valor_tabela", "0,00000000000000"))
            criar_tag(veiculacao, "Reaplicacao", "nao")
            desconto_radio = reg.get("desconto", "0,00000000000000")
            criar_tag(veiculacao, "Bonificacao", "sim" if numero_float(desconto_radio) == 100 else "nao")
            criar_tag(veiculacao, "DescontoNegociado", desconto_radio)
            criar_tag(veiculacao, "QuantidadeDeInsercoes", reg.get("insercoes", 0))
            criar_tag(veiculacao, "TipoDeCompra", reg.get("tipo_compra", "DETERMINADO"))

        criar_tag(veiculacao, "Cotacao", "")
        criar_tag(veiculacao, "IR", "")
        criar_tag(veiculacao, "IOF", "")
        criar_tag(veiculacao, "OutrosCustos", "")

        pais, estado, municipio = campos_territorio_xml(reg.get("cod_municipio", ""))
        criar_tag(veiculacao, "PaisesParaVeiculacao", pais)
        criar_tag(veiculacao, "EstadosParaVeiculacao", estado)
        criar_tag(veiculacao, "MunicipiosParaVeiculacao", municipio)

        criar_tag(veiculacao, "CNPJAgenciaResponsavel", "")
        criar_tag(veiculacao, "PercentualDescontoAgencia", "20,00")
        criar_tag(veiculacao, "PercentualRepasseAoOrgaoDescontoAgencia", "27,50")
        criar_tag(veiculacao, "Abatimento", "")
        criar_tag(veiculacao, "Justificativa", "")

        id_counter += 1

    ET.indent(root, space="  ", level=0)
    xml_str = ET.tostring(root, encoding="unicode", method="xml")
    xml_str = '<?xml version="1.0" encoding="ISO-8859-1"?>\n' + xml_str
    xml_str = re.sub(r"<([a-zA-Z0-9_]+) />", r"<\1></\1>", xml_str)
    return xml_str.encode("ISO-8859-1", errors="xmlcharrefreplace")

# -------------------------
# Processamento completo
# -------------------------

def processar_planilha(uploaded_file, ano_campanha):
    xls = pd.read_excel(uploaded_file, sheet_name=None, header=None)
    registros_radio = []
    registros_tv = []
    diagnostico = []

    for nome_aba, df in xls.items():
        linha_inicio = encontrar_inicio_triplo(df)
        if linha_inicio is None:
            continue

        tipo = detectar_tipo_midia(nome_aba, df)
        if tipo not in ["RADIO", "TV"]:
            continue
        if tipo == "RADIO" and "CONTRA PARTIDA" in texto_upper(nome_aba):
            continue

        mapa = mapear_colunas_triplas(df, linha_inicio, ano_campanha)
        faltantes = [campo for campo in ["ID_VEICULO", "DIAS"] if campo not in mapa or not mapa.get(campo)]
        periodo_global = detectar_periodo_global_aba(df, linha_inicio, mapa)
        periodo_txt = ""
        if periodo_global:
            periodo_txt = f"{formatar_data_obj(periodo_global[0])} a {formatar_data_obj(periodo_global[-1])}"
        qtd_validos = 0

        for row_idx in range(linha_inicio + 3, len(df)):
            row = df.iloc[row_idx].values
            reg = extrair_registro(tipo, row, mapa, periodo_global=periodo_global, nome_aba=nome_aba)
            if reg is None:
                continue
            qtd_validos += 1
            if tipo == "RADIO":
                registros_radio.append(reg)
            elif tipo == "TV":
                registros_tv.append(reg)

        diagnostico.append({
            "Aba": nome_aba,
            "Tipo": tipo,
            "Linha cabeçalho": linha_inicio + 1,
            "Período global da aba": periodo_txt,
            "Registros válidos": qtd_validos,
            "Colunas detectadas": ", ".join(k for k in mapa.keys() if k != "CANDIDATOS_NOME"),
            "Alertas": ", ".join(faltantes) if faltantes else "",
        })

    return registros_radio, registros_tv, pd.DataFrame(diagnostico)

# -------------------------
# Interface Streamlit
# -------------------------

st.set_page_config(page_title="Gerador XML V21", page_icon="📡", layout="wide")

st.title("Gerador de XML - V21")
st.markdown("Arraste a planilha **MS - CAMPANHA...xlsx** para gerar XML de TV e Rádio no padrão das planilhas oficiais.")

ano_campanha = st.number_input("Ano base da campanha", min_value=2020, max_value=2035, value=2026, step=1)
st.info("Regra V21: 1 linha válida = 1 veiculação. Datas são globais por aba, calculadas pela primeira e última inserção do grid da aba.")

uploaded_file = st.file_uploader("Upload da Planilha Excel", type=["xlsx"])

if uploaded_file is not None:
    try:
        with st.spinner("Processando planilha..."):
            registros_radio, registros_tv, diagnostico = processar_planilha(uploaded_file, int(ano_campanha))

        st.success("Análise concluída.")

        if not diagnostico.empty:
            st.subheader("Diagnóstico de abas")
            st.dataframe(diagnostico, use_container_width=True)

        col1, col2 = st.columns(2)

        with col1:
            if registros_radio:
                st.write(f"✅ Rádio: {len(registros_radio)} linhas válidas → {len(registros_radio)} veiculações no XML")
                xml_radio = gerar_conteudo_xml("RADIO", registros_radio, agrupar=False)
                st.download_button(
                    label="📻 Baixar XML Rádio V21",
                    data=xml_radio,
                    file_name="Radio_V21.xml",
                    mime="application/xml",
                )
            else:
                st.warning("Nenhum dado de Rádio encontrado.")

        with col2:
            if registros_tv:
                st.write(f"✅ TV: {len(registros_tv)} linhas válidas → {len(registros_tv)} veiculações no XML")
                xml_tv = gerar_conteudo_xml("TV", registros_tv, agrupar=False)
                st.download_button(
                    label="📺 Baixar XML TV V21",
                    data=xml_tv,
                    file_name="TV_V21.xml",
                    mime="application/xml",
                )
            else:
                st.warning("Nenhum dado de TV encontrado.")

    except Exception as e:
        st.error(f"Ocorreu um erro: {e}")
        st.exception(e)
