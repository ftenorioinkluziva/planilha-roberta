import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import re
import io
import unicodedata

# --- CONFIGURAÇÕES GERAIS ---
ANO_CAMPANHA = 2025

# --- FUNÇÕES DE LIMPEZA E TEXTO ---

def limpar_texto_agressivo(texto):
    if not texto: return ""
    texto_str = str(texto).strip()
    substituicoes = {'\xa0': ' ', '–': '-', '—': '-', '"': '"', '"': '"', '“': '"', '”': '"', '‘': "'", '’': "'", '…': '...'}
    for original, novo in substituicoes.items(): texto_str = texto_str.replace(original, novo)
    texto_norm = unicodedata.normalize('NFC', texto_str)
    return "".join(ch for ch in texto_norm if unicodedata.category(ch)[0] != "C" or ch in ['\n', '\t', '\r'])

# --- LÓGICA DE NEGÓCIO ---

def verificar_tipo_conteudo(df):
    """
    Varre as primeiras linhas para identificar se é Rádio ou TV pelo conteúdo.
    Retorna: 'RADIO', 'TV' ou None
    """
    # Converte as primeiras 20 linhas para uma string gigante para busca rápida
    try:
        sample = df.head(20).astype(str).to_string().upper()
        if "PROGRAMAÇÃO - RÁDIO" in sample or "PROGRAMAÇÃO - RADIO" in sample:
            return 'RADIO'
        if "PROGRAMAÇÃO - TELEVISÃO" in sample or "PROGRAMAÇÃO - TV" in sample or "PROGRAMAÇÃO - INTERNET" in sample:
            return 'TV'
    except: pass
    return None

def encontrar_inicio_triplo(df):
    for i in range(len(df) - 2):
        l1 = " ".join([str(x).upper() for x in df.iloc[i].values if pd.notna(x)])
        
        tem_id = "ID SECOM" in l1 or "ID. SECOM" in l1
        # Adiciona 'NOME FANTASIA' para pegar Rádio
        tem_campo_chave = "PROGRAMA" in l1 or "REDE" in l1 or "VEÍCULO" in l1 or "NOME FANTASIA" in l1
        
        if tem_id and tem_campo_chave:
            return i
    return None

def mapear_colunas_triplas(df, linha_inicio):
    row1 = df.iloc[linha_inicio].fillna('').astype(str).str.upper().str.strip()
    row2 = df.iloc[linha_inicio + 1].fillna('').astype(str).str.upper().str.strip()
    row3 = df.iloc[linha_inicio + 2].fillna('').astype(str).str.upper().str.strip()
    
    mapa = {'DIAS': []}
    last_r1 = ""
    mes_atual = 12 
    
    for idx in range(len(row1)):
        r1 = row1[idx]
        if r1 == "" and last_r1 != "": r1 = last_r1 
        else: last_r1 = r1  
        
        r2 = row2[idx]
        r3 = row3[idx]

        if "DEZEMBRO" in r1: mes_atual = 12
        elif "JANEIRO" in r1: mes_atual = 1
        elif "NOVEMBRO" in r1: mes_atual = 11

        if "ID SECOM" in r1 or "ID. SECOM" in r1: mapa['ID_VEICULO'] = idx
        if "REDE" in r1 or "NOME FANTASIA" in r1 or "VEÍCULO" in r1: 
             if 'NOME' not in mapa: mapa['NOME'] = idx
        
        # Ajuste para Rádio que às vezes não tem coluna PROGRAMA explícita
        if "PROGRAMA" in r1 and "HORÁRIO" not in r1: mapa['PROGRAMA'] = idx
        
        if "FORMATO" in r1 or "PEÇA" in r1: mapa['FORMATO'] = idx
        
        # Inserções
        termos_ins = ["INS", "TT. INS", "QTD", "TOTAL INSERÇÕES", "TT.INS", "TT INS"]
        eh_coluna_ins = any(t in r1.split() or t in r2.split() for t in termos_ins)
        nao_eh_valor = "VALOR" not in r1 and "CUSTO" not in r1 and "VALOR" not in r2
        if eh_coluna_ins and nao_eh_valor: mapa['INSERCOES'] = idx

        # Horários
        if "HORÁRIO" in r1 or "FAIXA HORÁRIA" in r1 or "FAIXA" in r1:
            if "INICIAL" in r2 or "INÍCIO" in r2: mapa['HORA_INI'] = idx
            if "FINAL" in r2 or "TÉRMINO" in r2: mapa['HORA_FIM'] = idx
        
        # Valores
        if ("VALOR" in r1 or "CUSTO" in r1) and "TABELA" in r1:
            if "UNITÁRIO" in r2 or "UNIT" in r2 or "30" in r2: 
                mapa['VALOR_TABELA'] = idx
        if "UNITÁRIO" in r2 and 'VALOR_TABELA' not in mapa: mapa['VALOR_TABELA'] = idx

        # Município
        if ("CÓD" in r1 or "COD" in r1) and ("MUN" in r1 or "IBGE" in r1): mapa['COD_MUNICIPIO'] = idx

        # Grid Dias
        if r3.isdigit():
            dia = int(r3)
            if 1 <= dia <= 31:
                ano = ANO_CAMPANHA
                if mes_atual == 1: ano = ANO_CAMPANHA + 1
                mapa['DIAS'].append({'idx': idx, 'dia': dia, 'mes': mes_atual, 'ano': ano})

    return mapa

def formatar_valor_br(valor):
    if pd.isna(valor) or str(valor).strip() == '': return "0,00000000000000"
    try:
        val_str = str(valor).replace('R$', '').replace(' ', '')
        if '.' in val_str and ',' in val_str: val_str = val_str.replace('.', '').replace(',', '.')
        val_float = round(float(val_str), 2)
        return f"{val_float:.14f}".replace('.', ',')
    except:
        return "0,00000000000000"

def formatar_horario(valor):
    if pd.isna(valor) or str(valor).strip() in ['-', 'nan', '']: return ""
    if hasattr(valor, 'strftime'): return valor.strftime('%H:%M')
    if isinstance(valor, (float, int)):
        if valor < 1: 
            segundos = int(valor * 24 * 3600)
            return (datetime(1900, 1, 1) + timedelta(seconds=segundos)).strftime('%H:%M')
    valor = str(valor).strip()
    match = re.search(r'(\d{1,2}:\d{2})', valor)
    if match: 
        h = match.group(1)
        return f"0{h}" if len(h) == 4 else h
    return ""

def formatar_data_obj(dt):
    return dt.strftime('%d/%m/%Y')

def processar_datas_grid(row, lista_dias):
    datas_validas = []
    for info in lista_dias:
        col_idx = info['idx']
        val = row[col_idx]
        tem_insercao = False
        try:
            val_str = str(val).strip()
            if pd.notna(val) and val_str not in ['', '-', 'nan', 'None', '0', '0.0']:
                tem_insercao = True
        except: pass
        if tem_insercao:
            datas_validas.append(datetime(info['ano'], info['mes'], info['dia']))
    if not datas_validas: return "", ""
    datas_validas.sort()
    return formatar_data_obj(datas_validas[0]), formatar_data_obj(datas_validas[-1])

def criar_tag(pai, nome, valor):
    elem = ET.SubElement(pai, nome)
    elem.text = limpar_texto_agressivo(valor)

def gerar_conteudo_xml(tipo_midia, dados_consolidados):
    root = ET.Element("documento")
    id_counter = 1
    
    for row_data in dados_consolidados:
        mapa = row_data['mapa']
        row = row_data['linha']
        
        if 'ID_VEICULO' not in mapa: continue
        id_veic_raw = str(row[mapa['ID_VEICULO']])
        if not id_veic_raw.replace('.','').replace(',','').isdigit(): continue
        
        veiculacao = ET.SubElement(root, "veiculacao", id=str(id_counter))
        
        id_veiculo = str(int(float(id_veic_raw)))
        data_ini, data_fim = processar_datas_grid(row, mapa['DIAS'])
        if not data_ini: data_ini = ""; data_fim = ""

        nome = str(row[mapa['NOME']]) if 'NOME' in mapa else ""
        programa = str(row[mapa['PROGRAMA']]).strip() if 'PROGRAMA' in mapa else "ROTATIVO"
        if tipo_midia == 'RADIO' and 'PROGRAMA' not in mapa: programa = "ROTATIVO"

        hora_ini = formatar_horario(row[mapa['HORA_INI']]) if 'HORA_INI' in mapa else "06:00"
        hora_fim = formatar_horario(row[mapa['HORA_FIM']]) if 'HORA_FIM' in mapa else ""
        if hora_ini and not hora_fim and 'HORA_INI' in mapa:
            try: hora_fim = formatar_horario(row[mapa['HORA_INI'] + 1])
            except: pass
        if not hora_fim: hora_fim = hora_ini

        insercoes = "0"
        if 'INSERCOES' in mapa:
            try: insercoes = str(int(float(row[mapa['INSERCOES']])))
            except: insercoes = "0"

        valor = "0,00000000000000"
        if 'VALOR_TABELA' in mapa:
            valor = formatar_valor_br(row[mapa['VALOR_TABELA']])
            
        formato = "30"
        if 'FORMATO' in mapa:
            val_fmt = str(row[mapa['FORMATO']]).replace('"', '').strip()
            if val_fmt.isdigit(): formato = val_fmt

        cod_municipio = ""
        if 'COD_MUNICIPIO' in mapa:
            try:
                val_mun = str(row[mapa['COD_MUNICIPIO']]).replace('.0', '').strip()
                if val_mun and val_mun.lower() not in ['nan', 'none', '', '-']:
                    cod_municipio = val_mun
            except: pass

        criar_tag(veiculacao, "IdentificadorVeiculacaoSistemaOrigem", id_counter)
        criar_tag(veiculacao, "TipoInformacao", "Planejado")
        criar_tag(veiculacao, "IdentificadorVeiculacao", "")
        criar_tag(veiculacao, "IdentificadorVeiculo", id_veiculo)
        
        if tipo_midia == 'RADIO': criar_tag(veiculacao, "IdNegociacao", "")
            
        criar_tag(veiculacao, "Nome", nome)
        criar_tag(veiculacao, "DataInicioDaVeiculacao", data_ini)
        criar_tag(veiculacao, "DataFimDaVeiculacao", data_fim)
        criar_tag(veiculacao, "Programa", programa)
        criar_tag(veiculacao, "FaixaHorariaInicial", hora_ini)
        criar_tag(veiculacao, "FaixaHorariaFinal", hora_fim)
        
        if tipo_midia == 'TV':
            criar_tag(veiculacao, "Bonificacao", "nao")
            criar_tag(veiculacao, "DescontoNegociado", "74,00000000000000")
            criar_tag(veiculacao, "QuantidadeDeInsercoes", insercoes)
            criar_tag(veiculacao, "FormatoTV", formato) 
            criar_tag(veiculacao, "CustoDeTabelaFormato", valor)
        elif tipo_midia == 'RADIO':
            criar_tag(veiculacao, "Formato", formato)
            criar_tag(veiculacao, "CustoDoFormato", valor)
            criar_tag(veiculacao, "Reaplicacao", "nao")
            criar_tag(veiculacao, "Bonificacao", "nao")
            criar_tag(veiculacao, "DescontoNegociado", "0,00000000000000")
            criar_tag(veiculacao, "QuantidadeDeInsercoes", insercoes)
            criar_tag(veiculacao, "TipoDeCompra", "ROTATIVO/INDETERMINADO")

        criar_tag(veiculacao, "Cotacao", "")
        criar_tag(veiculacao, "IR", "")
        criar_tag(veiculacao, "IOF", "")
        criar_tag(veiculacao, "OutrosCustos", "")
        
        if cod_municipio:
            criar_tag(veiculacao, "PaisesParaVeiculacao", "")
            criar_tag(veiculacao, "EstadosParaVeiculacao", "")
            criar_tag(veiculacao, "MunicipiosParaVeiculacao", cod_municipio)
        else:
            criar_tag(veiculacao, "PaisesParaVeiculacao", "BRA")
            criar_tag(veiculacao, "EstadosParaVeiculacao", "")
            criar_tag(veiculacao, "MunicipiosParaVeiculacao", "")

        criar_tag(veiculacao, "CNPJAgenciaResponsavel", "")
        criar_tag(veiculacao, "PercentualDescontoAgencia", "20,00")
        criar_tag(veiculacao, "PercentualRepasseAoOrgaoDescontoAgencia", "27,50")
        criar_tag(veiculacao, "Abatimento", "")
        criar_tag(veiculacao, "Justificativa", "")
        
        id_counter += 1

    ET.indent(root, space="  ", level=0)
    
    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    if not xml_str.startswith('<?xml'):
        header = '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        xml_str = header + xml_str
    xml_final_str = re.sub(r'<([a-zA-Z0-9_]+) />', r'<\1></\1>', xml_str)
    return xml_final_str.encode('ISO-8859-1', errors='xmlcharrefreplace')

# --- INTERFACE ---

st.set_page_config(page_title="Gerador XML V16", page_icon="📡")

st.title("Gerador de XML - V16 (Detecção Inteligente)")
st.markdown("Arraste a planilha **MS - CAMPANHA...xlsx**.")

uploaded_file = st.file_uploader("Upload da Planilha Excel", type=['xlsx'])

if uploaded_file is not None:
    st.info("Processando... Por favor aguarde.")
    
    try:
        xls = pd.read_excel(uploaded_file, sheet_name=None, header=None)
        
        dados_radio = []
        dados_tv = []
        
        progress_bar = st.progress(0)
        total_sheets = len(xls)
        
        for i, (nome_aba, df) in enumerate(xls.items()):
            linha_inicio = encontrar_inicio_triplo(df)
            
            if linha_inicio is not None:
                # DETECÇÃO HÍBRIDA (Nome da aba OU Conteúdo da planilha)
                tipo_detectado = verificar_tipo_conteudo(df)
                
                nome_upper = nome_aba.upper()
                eh_radio_nome = "RADIO" in nome_upper or "RÁDIO" in nome_upper or "RD " in nome_upper or "RD" in nome_upper
                eh_tv_nome = "TV" in nome_upper or "TELEVISÃO" in nome_upper or "CNN" in nome_upper or "REDE VIDA" in nome_upper
                
                eh_radio = (tipo_detectado == 'RADIO') or eh_radio_nome
                eh_tv = (tipo_detectado == 'TV') or eh_tv_nome
                
                if eh_radio or eh_tv:
                    mapa_cols = mapear_colunas_triplas(df, linha_inicio)
                    
                    for row_idx in range(linha_inicio + 3, len(df)):
                        row = df.iloc[row_idx].values
                        dados_brutos = {'mapa': mapa_cols, 'linha': row}
                        
                        if eh_radio: dados_radio.append(dados_brutos)
                        elif eh_tv: dados_tv.append(dados_brutos)
            
            progress_bar.progress((i + 1) / total_sheets)
            
        st.success("Análise concluída!")
        
        col1, col2 = st.columns(2)
        
        if dados_radio:
            st.write(f"✅ Rádio: {len(dados_radio)} veiculações")
            xml_radio = gerar_conteudo_xml('RADIO', dados_radio)
            col1.download_button(
                label="📻 Baixar XML Rádio",
                data=xml_radio,
                file_name="Radio_V16.xml",
                mime="application/xml"
            )
        else:
            col1.warning("Nenhum dado de Rádio encontrado.")

        if dados_tv:
            st.write(f"✅ TV: {len(dados_tv)} veiculações")
            xml_tv = gerar_conteudo_xml('TV', dados_tv)
            col2.download_button(
                label="📺 Baixar XML TV",
                data=xml_tv,
                file_name="TV_V16.xml",
                mime="application/xml"
            )
        else:
            col2.warning("Nenhum dado de TV encontrado.")
            
    except Exception as e:
        st.error(f"Ocorreu um erro: {e}")