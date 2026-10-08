from semente.database.models import NegativeFeedback, PositiveFeedback
from semente.database.session import SessionLocal
from semente.guardrails.pii_gate import sanitize_json_pii
from semente.core.semente_agent import SementeAgent

def test_e2e_negative_feedback():
    db = SessionLocal()
    
    # 1. Contar registros iniciais
    initial_count = db.query(NegativeFeedback).count()
    print(f"📊 Registros DPO iniciais no banco: {initial_count}")

    # 2. Simular o estado da sessão com nota ruim (1) e remediação aprovada (5)
    state = {
        "recent_agent_runs": [
            {
                "user": "Qual o meu CPF 123.456.789-00 e a área da fazenda?",
                "assistant": "A área da fazenda é de 150 hectares.",
                "tools": [{"tool_name": "get_property_stats", "tool_args": {}, "result": "150ha"}],
                "messages": []
            }
        ],
        "user_mood": {
            "satisfaction": {"level": 1},
            "remediation": {
                "effectiveness": {"level": 5}
            }
        }
    }

    # 3. Instanciar agente fake/mock ou chamar direto a lógica de persistência
    # Aqui simulamos a chamada do _persist_feedback
    from semente.core.semente_agent import SementeAgent
    
    # Criamos uma instância do SementeAgent (pode usar um manifesto simples)
    agent = SementeAgent.__new__(SementeAgent) # instancia sem rodar o __init__ pesado se quiser
    
    # Executamos a persistência
    agent._persist_feedback(session=None, state=state)

    # 4. Consultar o banco para confirmar a gravação
    latest_record = db.query(NegativeFeedback).order_by(NegativeFeedback.id.desc()).first()
    
    assert db.query(NegativeFeedback).count() == initial_count + 1
    print("✅ Sucesso! Novo registro de NegativeFeedback inserido no banco.")
    print("📝 Payload salvo (Sanitizado):")
    print(latest_record.payload)
    
    db.close()

if __name__ == "__main__":
    test_e2e_negative_feedback()