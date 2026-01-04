# NexusCoach API

Backend do NexusCoach - Coach de voz inteligente para Wild Rift.

## Sobre

API REST que processa as interacoes do usuario durante partidas de Wild Rift, fornecendo respostas estrategicas em tempo real atraves de:

- **NLU** - Processamento de linguagem natural para entender intencoes
- **Game Data** - Dados atualizados de campeoes, winrates, matchups e itens
- **LLM (Gemini)** - Geracao de respostas naturais e contextuais

## Tecnologias

- Python 3.11+
- FastAPI
- Gemini API (google-generativeai)
- SQLite
- Pydantic

## Instalacao

```bash
# Clonar o repositorio
git clone https://github.com/seu-usuario/NexusCoachApi.git
cd NexusCoachApi

# Criar ambiente virtual
python -m venv .venv

# Ativar (Windows)
.venv\Scripts\activate

# Ativar (Linux/Mac)
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

## Configuracao

Crie um arquivo `.env` ou configure as variaveis de ambiente:

```env
GEMINI_API_KEY=sua_chave_aqui
GEMINI_MODEL=gemini-2.0-flash-exp
LLM_PROVIDER=gemini
DATABASE_URL=sqlite:///./nexuscoach.db
```

### Todas as Variaveis

| Variavel | Descricao | Default |
|----------|-----------|---------|
| `GEMINI_API_KEY` | Chave da API do Gemini | (obrigatorio) |
| `GEMINI_MODEL` | Modelo do Gemini | `gemini-2.0-flash-exp` |
| `LLM_PROVIDER` | Provider do LLM (`gemini` ou `rules`) | `gemini` |
| `DATABASE_URL` | URL do banco SQLite | `sqlite:///./nexuscoach.db` |
| `MAX_HISTORY` | Maximo de mensagens no historico | `20` |
| `SESSION_TTL_SECONDS` | Tempo de vida da sessao | `21600` (6h) |

## Executando

```bash
# Desenvolvimento
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Producao
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`

## Estrutura do Projeto

```
app/
├── main.py         # Endpoints da API
├── config.py       # Configuracoes e variaveis de ambiente
├── models.py       # Modelos Pydantic (request/response)
├── store.py        # Gerenciamento de sessoes em memoria
├── db.py           # Persistencia SQLite (feedback)
├── nlu.py          # Processamento de linguagem natural
├── strategy.py     # Motor de estrategia e regras
├── llm.py          # Integracao com Gemini
├── game_data.py    # Dados de campeoes e itens do Wild Rift
├── i18n.py         # Internacionalizacao (PT-BR, EN-US)
├── stt.py          # Speech-to-text (preparado)
└── errors.py       # Tratamento de erros
```

## API Endpoints

### Sessao

#### `POST /session/start`
Inicia uma nova sessao de coaching.

```json
// Request
{
  "device_id": "unique-device-id",
  "locale": "pt-BR",
  "champion": "Camille",
  "lane": "top",
  "enemy": "Darius"
}

// Response
{
  "session_id": "uuid",
  "greeting": "Ola! Voce esta de Camille no top contra Darius..."
}
```

#### `POST /session/{session_id}/turn`
Envia uma mensagem e recebe resposta do coach.

```json
// Request
{
  "text": "to com 1200 de ouro, qual item compro?"
}

// Response
{
  "reply_text": "Com 1200 de ouro, compre Placas de Aco...",
  "intent": "ask_build",
  "updated_state": { ... }
}
```

#### `POST /session/{session_id}/end`
Encerra a sessao com feedback opcional.

```json
// Request
{
  "feedback_rating": "good"
}

// Response
{ "ok": true }
```

### Admin

| Endpoint | Descricao |
|----------|-----------|
| `POST /admin/sync-game-data` | Sincroniza dados de campeoes |
| `GET /admin/champion/{name}` | Info de um campeao |
| `GET /admin/item/{name}` | Info de um item |
| `GET /admin/items` | Lista todos os itens |

## NLU - Intencoes

O sistema reconhece as seguintes intencoes:

| Intencao | Exemplos |
|----------|----------|
| `ask_build` | "qual item?", "proximo item", "build" |
| `ask_matchup` | "como jogo contra?", "matchup", "dicas" |
| `ask_macro` | "faco dragao?", "split ou grupo?" |
| `ask_status` | "to ganhando?", "situacao" |
| `update_gold` | "1200 de ouro", "tenho 3k" |
| `update_status` | "to fed", "morri 3x", "to atras" |
| `update_enemy_status` | "yasuo ta fed", "adc fraco" |

### Deteccao de Multiplos Inimigos

O NLU detecta automaticamente multiplos campeoes mencionados:

```
"to contra jax no top mas caitlyn e nami tao fed"
```

Resulta em analise de composicao do time inimigo com:
- Tipo de dano predominante (fisico/magico)
- Presenca de healers, tanks, assassinos
- Sugestao de itens defensivos

## Game Data

Dados incluidos:

- **80+ Campeoes** - roles, dificuldade, tipo de dano
- **Winrates** - por lane, atualizados
- **60+ Itens** - stats, passivas, tags
- **Matchup Tips** - dicas para combinacoes comuns
- **Counter Items** - itens recomendados contra tipos de inimigo

## Fluxo de Processamento

```
Usuario: "to com 1500 de ouro contra darius, qual item?"
                    │
                    ▼
            ┌──────────────┐
            │     NLU      │
            │  intencao:   │
            │  ask_build   │
            │  gold: 1500  │
            │  enemy: dar  │
            └──────────────┘
                    │
                    ▼
            ┌──────────────┐
            │  Strategy    │
            │  - matchup   │
            │  - fase      │
            │  - status    │
            └──────────────┘
                    │
                    ▼
            ┌──────────────┐
            │  Game Data   │
            │  - winrates  │
            │  - itens     │
            │  - counters  │
            └──────────────┘
                    │
                    ▼
            ┌──────────────┐
            │   Gemini     │
            │  (prompt c/  │
            │   contexto)  │
            └──────────────┘
                    │
                    ▼
        "Compre Placa de Aco e Botas..."
```

## Testes

```bash
# Health check
curl http://localhost:8000/health

# Iniciar sessao
curl -X POST http://localhost:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{"device_id":"test","locale":"pt-BR","champion":"Yasuo","lane":"mid"}'

# Enviar mensagem
curl -X POST http://localhost:8000/session/{session_id}/turn \
  -H "Content-Type: application/json" \
  -d '{"text":"qual item contra zed?"}'
```

## Disclaimer

Este projeto nao e afiliado a Riot Games. Wild Rift e marca registrada da Riot Games.
