import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import re

# Configurações de Arquivos
ARQUIVO_CAMPANHA = 'MS - CAMPANHA AGORA TEM ESPECIALISTAS.xlsx' # Nome do seu arquivo real

# Dicionário de padronização de colunas (O Excel tem nomes variados para a mesma coisa)
MAPA_COLUNAS = {
    'ID_VEICULO': ['ID. SECOM', 'ID SECOM', 'CÓDIGO', 'ID'],
    'NOME': ['NOME FANTASIA', 'VEÍCULO', 'EMISSORA', 'REDE'],
    'INICIO': ['INÍCIO', 'DATA INÍCIO', 'PERÍODO DE VEICULAÇÃO', 'INICIAL'],
    'FIM': ['FIM', 'DATA FIM', 'FINAL'],
    'INSERCOES': ['TT. INS.', 'TOTAL', 'QTD. INSERÇÕES', 'INS'],
    'VALOR': ['CUSTO NEGOCIADO', 'VALOR NEGOCIADO', 'TOTAL (NEGOCIADO)'],
    'FORMATO': ['FORMATO', 'DUR.', 'SECUNDAGEM']
}

def encontrar_inicio_tabela(df_raw, palavra_chave):
    """
    Procura a palavra chave e retorna a linha onde o cabeçalho da tabela provavelmente está.
    """
    for index, row in df_raw.iterrows():
        # Converte a linha para string e busca a palavra chave
        linha_texto = " ".join([str(val) for val in row.values if pd.notna(val)]).upper()
        
        if palavra_chave in linha_texto:
            # Se achou o título "PROGRAMAÇÃO...", procura o cabeçalho real nas próximas 10 linhas
            for i in range(1, 15):
                if index + i >= len(df_raw): break
                row_check = df_raw.iloc[index + i]
                linha_check = " ".join([str(val) for val in row_check.values if pd.notna(val)]).upper()
                
                # Se a linha tiver "ID SECOM" ou "ID. SECOM", é o cabeçalho
                if "ID SECOM" in linha_check or "ID. SECOM" in linha_check:
                    return index + i
    return None

def normalizar_coluna(col_name):
    """Tenta encontrar o nome padrão para uma coluna do Excel"""
    col_name = str(col_name).upper().strip()
    for chave, lista_possiveis in MAPA_COLUNAS.items():
        for possivel in lista_possiveis:
            if possivel in col_name:
                return chave
    return col_name

def formatar_numero_br(valor):
    """Converte número Python (ponto) para XML Br (vírgula)"""
    if pd.isna(valor): return "0,00"
    try:
        return f"{float(valor):.2f}".replace('.', ',')
    except:
        return str(valor)

def formatar_data(data):
    """Garante formato DD/MM/AAAA"""
    if pd.isna(data) or data == '-': return ""
    if isinstance(data, datetime):
        return data.strftime('%d/%m/%Y')
    try:
        # Tenta converter string se vier texto
        return pd.to_datetime(data, dayfirst=True).strftime('%d/%m/%Y')
    except:
        return str(data) # Retorna como está se falhar

def gerar_xml(tipo_midia, dados_consolidados, nome_arquivo_saida):
    root = ET.Element("documento")
    id_counter = 1
    
    for row in dados_consolidados:
        veiculacao = ET.SubElement(root, "veiculacao", id=str(id_counter))
        
        # Campos Comuns
        ET.SubElement(veiculacao, "IdentificadorVeiculacaoSistemaOrigem").text = str(id_counter)
        ET.SubElement(veiculacao, "TipoInformacao").text = "Planejado"
        
        # Tratamento seguro para ID Veículo (remove .0 se for float)
        id_bruto = row.get('ID_VEICULO', '')
        try:
            id_veic = str(int(float(id_bruto)))
        except:
            id_veic = str(id_bruto)
            
        ET.SubElement(veiculacao, "IdentificadorVeiculo").text = id_veic
        ET.SubElement(veiculacao, "Nome").text = str(row.get('NOME', ''))
        ET.SubElement(veiculacao, "DataInicioDaVeiculacao").text = formatar_data(row.get('INICIO'))
        ET.SubElement(veiculacao, "DataFimDaVeiculacao").text = formatar_data(row.get('FIM'))
        ET.SubElement(veiculacao, "Programa").text = "ROTATIVO" # Ou extrair da coluna PROGRAMA se existir
        
        # Horários (Padrão genérico, ideal tentar extrair se houver coluna)
        ET.SubElement(veiculacao, "FaixaHorariaInicial").text = "06:00"
        ET.SubElement(veiculacao, "FaixaHorariaFinal").text = "19:00"
        
        # Diferenças entre XML de TV e Rádio
        if tipo_midia == 'TV':
            ET.SubElement(veiculacao, "FormatoTV").text = str(row.get('FORMATO', '30')).replace('"', '')
            ET.SubElement(veiculacao, "CustoDeTabelaFormato").text = formatar_numero_br(row.get('VALOR')) # Usando valor negoociado como exemplo
        else:
            ET.SubElement(veiculacao, "Formato").text = str(row.get('FORMATO', '30')).replace('"', '')
            ET.SubElement(veiculacao, "CustoDoFormato").text = formatar_numero_br(row.get('VALOR'))

        ET.SubElement(veiculacao, "QuantidadeDeInsercoes").text = str(int(row.get('INSERCOES', 0)) if pd.notna(row.get('INSERCOES')) else 0)
        ET.SubElement(veiculacao, "Bonificacao").text = "nao"
        ET.SubElement(veiculacao, "Reaplicacao").text = "nao"
        
        id_counter += 1

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(nome_arquivo_saida, encoding="ISO-8859-1", xml_declaration=True)
    print(f"Arquivo '{nome_arquivo_saida}' gerado com {id_counter-1} veiculações.")

# --- EXECUÇÃO PRINCIPAL ---

# 1. Carregar todas as abas (None lê todas)
print("Lendo arquivo Excel... (isso pode demorar um pouco)")
xls = pd.read_excel(ARQUIVO_CAMPANHA, sheet_name=None, header=None)

dados_radio = []
dados_tv = []

# 2. Iterar sobre cada aba e procurar os padrões
for nome_aba, df in xls.items():
    print(f"Analisando aba: {nome_aba}")
    
    # Verifica se é Rádio
    linha_header_radio = encontrar_inicio_tabela(df, "PROGRAMAÇÃO - RÁDIO")
    if linha_header_radio:
        print(f"  -> Encontrado bloco de RÁDIO na linha {linha_header_radio}")
        # Recarrega a aba definindo o header correto
        df_real = pd.read_excel(ARQUIVO_CAMPANHA, sheet_name=nome_aba, header=linha_header_radio)
        
        # Normaliza colunas
        df_real.columns = [normalizar_coluna(col) for col in df_real.columns]
        
        # Filtra apenas linhas que tenham ID Veículo (descarta rodapés/totais)
        if 'ID_VEICULO' in df_real.columns:
            df_limpo = df_real.dropna(subset=['ID_VEICULO'])
            dados_radio.extend(df_limpo.to_dict('records'))

    # Verifica se é TV
    linha_header_tv = encontrar_inicio_tabela(df, "PROGRAMAÇÃO - TELEVISÃO")
    if linha_header_tv:
        print(f"  -> Encontrado bloco de TV na linha {linha_header_tv}")
        df_real = pd.read_excel(ARQUIVO_CAMPANHA, sheet_name=nome_aba, header=linha_header_tv)
        
        df_real.columns = [normalizar_coluna(col) for col in df_real.columns]
        
        if 'ID_VEICULO' in df_real.columns:
            df_limpo = df_real.dropna(subset=['ID_VEICULO'])
            dados_tv.extend(df_limpo.to_dict('records'))

# 3. Gerar os arquivos XML
if dados_radio:
    gerar_xml('RADIO', dados_radio, "Radio_Automated.xml")
else:
    print("Nenhum dado de Rádio encontrado.")

if dados_tv:
    gerar_xml('TV', dados_tv, "TV_Automated.xml")
else:
    print("Nenhum dado de TV encontrado.")