# 🚀 CadêMinhasHoras: Seu Assistente Pessoal e Gestor de SAs (Telegram + Gemini)

Assistente pessoal para o dia a dia de trabalho: responde a perguntas em áudio ou texto, consulta histórico de tarefas, gera scripts de **Daily Meeting**, captura **pendências e to-dos**, mantém **bloco de notas diário**, agenda **alarmes de ponto** e gera **relatórios consolidados de SAs em Excel (`.xlsx`)**.

---

### Como Interagir no Dia a Dia (Áudio ou Texto)
- **Perguntas Gerais e Dúvidas:**
  - *"Quando foi a última vez que trabalhei na SA do refin?"*
  - *"Quantas horas já lancei essa semana?"*
  - *"Como tá o tempo hoje?"* ou *"Qual a previsão de chuva?"*
- **Lançamento de Horas com Apelidos:**
  - *"Gastei 3h no refin ajustando as queries do banco"* ➡️ Lança direto na SA associada.
- **Bloco de Notas (Sem SA):**
  - *"Participei da daily com o time e ajudei no deploy de homologação"* ➡️ Salva como diário cronológico.
- **Captura Automática de Pendências:**
  - *"Fiz 2h no refin, mas ainda preciso cobrar o Matheus sobre o schema do banco"* ➡️ Registra a SA e cria uma tarefa pendente em `/tarefas` com botão para concluir!

### Comandos Úteis
- `/daily` - Gera a sua fala pronta para a reunião de Daily Meeting de hoje.
- `/tarefas` (ou `/todo`) - Lista suas pendências com botão `[✅ Concluir]`.
- `/escrever <ideia>` - Redige uma mensagem ou e-mail corporativo polido e profissional.
- `/hoje` - Resumo do dia (Horas nas SAs + Bloco de Notas). Suporta `/hoje ontem` ou `/dia DD/MM/AAAA`.
- `/notas` - Lista apenas as anotações do bloco de notas do dia.
- `/mes` - Envia o resumo mensal agrupado por SA e a planilha Excel formatada.
- `/apelidos` - Lista todos os projetos/apelidos vinculados a cada SA.
- `/apelido <nome> <numero>` - Cadastra manualmente um apelido para uma SA.
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

