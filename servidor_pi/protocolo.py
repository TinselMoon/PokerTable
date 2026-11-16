import json


def empacotar(tipo: str, **dados) -> bytes:
    """Cria uma mensagem padronizada no formato {'tipo': ..., 'dados': {...}}\n."""
    envelope = {"tipo": tipo, "dados": dados}
    return (json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8")


def desempacotar(linha: str) -> tuple[str, dict]:
    """Extrai (tipo, dados) de uma linha JSON recebida pelo socket."""
    envelope = json.loads(linha)
    return envelope.get("tipo", ""), envelope.get("dados", {})
