# 🚀 Bot de Rastro Diário de Horas em SAs (Telegram + Gemini)

Assistente pessoal para registrar o tempo gasto em cada Ordem de Serviço / SA ao longo do dia via **mensagens de texto** ou **áudio** no Telegram. Ao final do mês, gera relatório consolidado agrupado por SA e planilha Excel (`.xlsx`) pronta para copiar e colar no sistema corporativo.

---

## 🛠️ Pré-requisitos e Configuração

### 1. Obter Token do Telegram
1. Abra o Telegram e procure por `@BotFather`.
2. Envie `/newbot` e siga as instruções para definir o nome e username do seu bot.
3. Copie o **Token HTTP API** gerado (ex: `123456789:ABCdefGhIJKlmNo...`).

### 2. Obter Chave do Google Gemini (Gratuita)
1. Acesse o [Google AI Studio](https://aistudio.google.com/).
2. Clique em **Get API Key** e copie a sua chave.

### 3. Configurar Variáveis de Ambiente
Crie um arquivo `.env` na raiz da pasta do projeto (você pode duplicar o `.env.example`):
```env
TELEGRAM_BOT_TOKEN=seu_telegram_bot_token_aqui
GEMINI_API_KEY=sua_gemini_api_key_aqui
ALLOWED_TELEGRAM_USER_ID=
```

*(Opcional: deixe `ALLOWED_TELEGRAM_USER_ID` em branco no primeiro momento. Ao dar `/start` no bot, ele informará seu ID numérico. Depois você pode colá-lo aqui para garantir que ninguém mais acesse seu bot).*

---

## 📦 Instalação

Abra o terminal na pasta do projeto e instale as dependências:
```bash
pip install -r requirements.txt
```

---

## ▶️ Como Rodar

Execute o arquivo principal:
```bash
python bot.py
```

---

## 💬 Como Usar no Dia a Dia

### Registrando Horas
- **Texto Livre:**
  - *"Passei a manhã inteira (4h) na SA 8912 refatorando as queries do banco"*
  - *"Fiz 1h30 na SA 1024 alinhando os requisitos com o cliente"*
  - *"Ontem trabalhei 2h na SA 5543 ajustando o layout"*
- **Áudio:**
  - Apenas mande um áudio no Telegram falando naturalmente: *"Ô bot, acabei de gastar duas horas na SA 4321 consertando o bug de login."*
- O bot processa o texto/áudio, extrai com precisão a SA, horas e descrição, e devolve a confirmação com um botão para **Desfazer** se necessário.

### Comandos Úteis
- `/hoje` - Lista o resumo completo do dia (Horas nas SAs + Anotações do Bloco de Notas).
- `/notas` - Lista apenas as anotações do bloco de notas do dia.
- `/mes` - Envia o resumo completo de horas acumuladas no mês (agrupado por SA) e um arquivo Excel (`.xlsx`) formatado.
- `/apelidos` - Lista todos os projetos/apelidos vinculados a cada SA.
- `/apelido <nome> <numero>` - Cadastra manualmente um apelido para uma SA (ex: `/apelido refin 96569`).
- `/alarmes` - Ativa ou pausa os alarmes automáticos de ponto no Telegram.
- `/desfazer` - Remove o último lançamento registrado de SA.

---

## ⏰ Alarmes Automáticos de Ponto (Segunda a Sexta)
O bot agenda notificações automáticas no fuso horário de Brasília:
1. **08:00** - 🟢 Bater ponto de entrada.
2. **12:00** - 🍽️ Pausa para almoço + Lembrança do que foi feito de manhã (com resumo das horas já registradas).
3. **12:30** - 🍲 Lembrete flexível de almoço (caso saia entre 12h e 13h).
4. **13:30** - 💻 Retorno do almoço (bater ponto de volta).
5. **17:00** - 🏁 Fim de expediente (bater ponto de saída + fechamento e registro das horas da tarde).

---

## ☁️ Deploy Gratuito no Render.com (24/7)

O bot já possui um servidor web leve (FastAPI) embutido para responder ao Render e a serviços de monitoramento.

### 1. Criar Web Service no Render
1. Suba o código para um repositório no seu GitHub.
2. Acesse o painel do [Render](https://dashboard.render.com/) e clique em **New +** > **Web Service**.
3. Selecione o repositório do projeto.
4. Preencha as configurações:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Plan:** `Free`
5. Na seção **Environment Variables**, adicione:
   - `TELEGRAM_BOT_TOKEN` = `seu_token_do_botfather`
   - `GEMINI_API_KEY` = `sua_chave_do_gemini`
   - `ALLOWED_TELEGRAM_USER_ID` = `seu_id_do_telegram`
   - `PORT` = `10000` *(ou deixe o Render injetar a porta padrão)*
6. Clique em **Create Web Service**.

### 2. Evitar que o Render Durma (UptimeRobot - Gratuito)
Como o plano gratuito do Render hiberna após 15 minutos sem requisições HTTP (o que pararia os alarmes de ponto):
1. Copie a URL do seu serviço no Render (ex: `https://meu-bot-pontos.onrender.com`).
2. Acesse o [UptimeRobot](https://uptimerobot.com/) (gratuito) e crie um monitor:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Bot Ponto`
   - **URL (or IP):** Cole a URL do Render
   - **Monitoring Interval:** a cada `5` ou `10` minutos.
3. Pronto! O bot ficará **acordado 24 horas por dia**, garantindo que seus alarmes das 8h, 12h e 17h disparem no horário certo.

