# Usa uma imagem leve do Python
FROM python:3.9-slim

# Define a pasta de trabalho dentro do container
WORKDIR /app

# Instala dependências do sistema necessárias (opcional, mas bom para garantir)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copia os arquivos do projeto para o container
COPY . .

# Instala as bibliotecas do Python
RUN pip3 install -r requirements.txt

# Expõe a porta que o Streamlit usa
EXPOSE 8501

# Comando para verificar se o container está saudável
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Comando para iniciar o aplicativo
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]