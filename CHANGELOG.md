# Changelog

Todas as mudancas notaveis deste projeto serao documentadas neste arquivo.

O formato e baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [Unreleased]

## [0.1.0] - 2025-01

### Adicionado

#### Core
- Estrutura inicial da API com FastAPI
- Configuracao via variaveis de ambiente (`.env`)
- Gerenciamento de sessoes em memoria com TTL configuravel
- Persistencia de feedback em SQLite

#### Endpoints
- `POST /session/start` - Inicia sessao de coaching
- `POST /session/{id}/turn` - Processa turno de conversa
- `POST /session/{id}/end` - Encerra sessao com feedback
- `GET /health` - Health check
- Endpoints admin para sync e consulta de dados de jogo

#### NLU (Natural Language Understanding)
- Classificador de intencoes por regras e keywords
- Intencoes: `ask_build`, `ask_matchup`, `ask_macro`, `ask_status`
- Intencoes de update: `update_gold`, `update_status`, `update_enemy_status`
- Deteccao de multiplos campeoes inimigos na mesma frase
- Extracao de slots: gold, status, campeao, lane

#### Game Data
- Base de dados de 80+ campeoes do Wild Rift
- Informacoes: roles, dificuldade, tipo de dano, winrates por lane
- Base de dados de 60+ itens com stats e passivas
- Tags de itens para recomendacao contextual
- Sistema de matchup tips para combinacoes comuns
- Counter items por tipo de inimigo

#### LLM Integration
- Integracao com Gemini API (google-generativeai)
- Sistema de prompts com contexto de partida
- Guardrails para respostas curtas e focadas
- Analise de composicao de time inimigo
- Sugestoes de itens defensivos baseadas em comp

#### Internacionalizacao
- Suporte a PT-BR e EN-US
- Traducoes para todas as mensagens do sistema

### Seguranca
- Rate limiting por sessao
- Validacao de inputs com Pydantic
- Sanitizacao de dados de usuario
