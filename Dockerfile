FROM python:3.9-slim

WORKDIR /app

# Instala APENAS o essencial para compilar bibliotecas Python
# Removemos 'software-properties-common' e 'git' que estavam dando erro
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia os arquivos do projeto
COPY . .

# Instala as dependências do requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]