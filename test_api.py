#!/usr/bin/env python
"""Script de teste da API."""
import requests

BASE = "http://localhost:8000"

# 1. Criar sessao
print("1. Criando sessao...")
r = requests.post(f"{BASE}/session/start", json={
    "locale": "pt-BR",
    "device_id": "test-script-2",
    "initial_context": {"champion": "Yasuo", "lane": "mid", "enemy": "Zed"}
})
data = r.json()
session_id = data["data"]["session_id"]
print(f"   Session ID: {session_id}")

# 2. Fazer pergunta - agora deve considerar a correcao aprendida!
print("\n2. Perguntando sobre Zed (deve considerar correcao sobre shuriken)...")
r = requests.post(f"{BASE}/turn", json={
    "session_id": session_id,
    "text": "como evito o dano do Zed?",
    "context": {}
})
reply = r.json()["data"]["reply_text"]
print(f"   Resposta: {reply}")

# 3. Finalizar com feedback positivo
print("\n3. Enviando feedback positivo...")
r = requests.post(f"{BASE}/session/end", json={
    "session_id": session_id,
    "feedback": {"rating": "good"}
})
print(f"   Status: {r.status_code}")

print("\nTeste concluido!")
