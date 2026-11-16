from treys import Card, Evaluator


class JogoPoker:
    def __init__(self):
        self.evaluator = Evaluator()
        self.jogadores = {}  # {conn: {"nome": str, "saldo": float, "mao": list, "aposta_rodada": float, "ativo": bool}}
        self.cartas_mesa = []
        self.pote = 0.0
        self.aposta_atual = 0.0
        self.fase = "AGUARDANDO"
        self.aguardando_cartas = 0
        self.indice_carta_privada = 0
        self.indice_turno = 0
        self.acoes_na_rodada = 0

    def _conns_registradas(self) -> list:
        return list(self.jogadores.keys())

    def registrar_jogador(self, conn, nome: str, saldo: float) -> list[tuple]:
        self.jogadores[conn] = {
            "nome": nome,
            "saldo": float(saldo),
            "mao": [],
            "aposta_rodada": 0.0,
            "ativo": True,
        }
        return self._gerar_estado_individualizado(
            f"{nome} entrou na mesa. Clique em 'Nova Rodada' quando todos entrarem."
        )

    def remover_jogador(self, conn) -> list[tuple]:
        jogador = self.jogadores.pop(conn, None)
        if not jogador:
            return []
        if self.jogadores:
            self.indice_turno %= len(self.jogadores)
        return self._gerar_estado_individualizado(f"{jogador['nome']} saiu da mesa.")

    def iniciar_nova_rodada(self) -> list[tuple]:
        if len(self.jogadores) < 1:
            return self._gerar_estado_individualizado(
                "Aguardando pelo menos 2 jogadores conectarem..."
            )

        self.cartas_mesa.clear()
        self.pote = 0.0
        self.aposta_atual = 0.0
        self.fase = "PRE_FLOP"
        self.aguardando_cartas = len(self.jogadores) * 2
        self.indice_carta_privada = 0

        for j in self.jogadores.values():
            j["mao"].clear()
            j["aposta_rodada"] = 0.0
            j["ativo"] = True

        mensagens = [("TODOS", "nova_rodada", {})]
        mensagens.extend(
            self._gerar_estado_individualizado(
                f"Pré-Flop: escaneie {self.aguardando_cartas} cartas ({len(self.jogadores)} jogadores x 2)."
            )
        )
        return mensagens

    def processar_carta_lida(self, carta: str) -> list[tuple]:
        if self.aguardando_cartas <= 0:
            return self._gerar_estado_individualizado(
                "Aguarde o fim das apostas antes de escanear mais cartas."
            )

        mensagens = []
        conns = self._conns_registradas()

        if self.fase == "PRE_FLOP":
            conn_alvo = conns[self.indice_carta_privada % len(conns)]
            self.jogadores[conn_alvo]["mao"].append(carta)
            self.indice_carta_privada += 1
            self.aguardando_cartas -= 1

            # Envio unicast apenas para o socket do dono da carta
            mensagens.append((conn_alvo, "carta_mao", {"carta": carta}))

            if self.aguardando_cartas == 0:
                mensagens.extend(
                    self._iniciar_rodada_apostas(
                        "Cartas entregues! Rodada de apostas Pré-Flop."
                    )
                )
            else:
                proximo = self.jogadores[conns[self.indice_carta_privada % len(conns)]][
                    "nome"
                ]
                mensagens.extend(
                    self._gerar_estado_individualizado(
                        f"Carta entregue. Próxima carta para: {proximo}"
                    )
                )

        elif self.fase in ("FLOP", "TURN", "RIVER"):
            self.cartas_mesa.append(carta)
            self.aguardando_cartas -= 1
            mensagens.append(("TODOS", "carta_mesa", {"carta": carta}))

            if self.aguardando_cartas == 0:
                mensagens.extend(
                    self._iniciar_rodada_apostas(
                        f"{self.fase} na mesa! Façam suas apostas."
                    )
                )
            else:
                mensagens.extend(
                    self._gerar_estado_individualizado(
                        f"{self.fase}: faltam {self.aguardando_cartas} carta(s)."
                    )
                )

        return mensagens

    def processar_acao(self, conn, acao: str, valor: float = 0.0) -> list[tuple]:
        conns = self._conns_registradas()
        if self.aguardando_cartas > 0 or not conns or conn not in self.jogadores:
            return []
        if conns[self.indice_turno] != conn:
            return [(conn, "erro", {"msg": "Não é a sua vez!"})]

        jogador = self.jogadores[conn]
        nome = jogador["nome"]
        a_pagar = max(0.0, self.aposta_atual - jogador["aposta_rodada"])
        aviso = ""

        if acao == "fold":
            jogador["ativo"] = False
            aviso = f"{nome} correu (Fold)."

        elif acao == "check":
            if a_pagar > 0:
                return [
                    (
                        conn,
                        "erro",
                        {"msg": f"Você precisa pagar R${a_pagar:.0f} ou correr."},
                    )
                ]
            aviso = f"{nome} passou (Check)."

        elif acao == "call":
            pagamento = min(a_pagar, jogador["saldo"])
            jogador["saldo"] -= pagamento
            jogador["aposta_rodada"] += pagamento
            self.pote += pagamento
            aviso = f"{nome} pagou R${pagamento:.0f} (Call)."

        elif acao == "raise":
            total_necessario = a_pagar + valor
            if valor <= 0 or jogador["saldo"] < total_necessario:
                return [
                    (
                        conn,
                        "erro",
                        {"msg": "Valor de aumento inválido ou saldo insuficiente."},
                    )
                ]
            jogador["saldo"] -= total_necessario
            jogador["aposta_rodada"] += total_necessario
            self.aposta_atual = jogador["aposta_rodada"]
            self.pote += total_necessario
            self.acoes_na_rodada = 0
            aviso = f"{nome} aumentou para R${self.aposta_atual:.0f} (Raise)!"

        self.acoes_na_rodada += 1

        ativos = [c for c, j in self.jogadores.items() if j["ativo"]]
        if len(ativos) == 1:
            vencedor = self.jogadores[ativos[0]]
            vencedor["saldo"] += self.pote
            self.fase = "SHOWDOWN"
            return self._gerar_estado_individualizado(
                f"{aviso} Todos correram! {vencedor['nome']} ganhou R${self.pote:.0f}!"
            )

        todos_igualaram = all(
            self.jogadores[c]["aposta_rodada"] == self.aposta_atual
            or self.jogadores[c]["saldo"] == 0
            for c in ativos
        )
        if todos_igualaram and self.acoes_na_rodada >= len(ativos):
            return self._avancar_fase(aviso)

        self._avancar_turno()
        return self._gerar_estado_individualizado(aviso)

    def _iniciar_rodada_apostas(self, msg: str) -> list[tuple]:
        self.aposta_atual = 0.0
        self.acoes_na_rodada = 0
        for j in self.jogadores.values():
            j["aposta_rodada"] = 0.0
        self.indice_turno = 0
        conns = self._conns_registradas()
        if not self.jogadores[conns[0]]["ativo"]:
            self._avancar_turno()
        return self._gerar_estado_individualizado(msg)

    def _avancar_turno(self):
        conns = self._conns_registradas()
        total = len(conns)
        for _ in range(total):
            self.indice_turno = (self.indice_turno + 1) % total
            if self.jogadores[conns[self.indice_turno]]["ativo"]:
                break

    def _avancar_fase(self, ultimo_aviso: str) -> list[tuple]:
        transicoes = {
            "PRE_FLOP": ("FLOP", 3),
            "FLOP": ("TURN", 1),
            "TURN": ("RIVER", 1),
            "RIVER": ("SHOWDOWN", 0),
        }
        nova_fase, qtd_cartas = transicoes[self.fase]
        self.fase = nova_fase
        self.aguardando_cartas = qtd_cartas

        if nova_fase == "SHOWDOWN":
            return self._avaliar_showdown(ultimo_aviso)

        return self._gerar_estado_individualizado(
            f"{ultimo_aviso} Fim das apostas. Escaneie {qtd_cartas} carta(s) para o {nova_fase}."
        )

    def _avaliar_showdown(self, ultimo_aviso: str) -> list[tuple]:
        board_treys = [Card.new(c) for c in self.cartas_mesa]
        melhor_score = 9999
        vencedores = []
        melhor_classe = ""

        for j in self.jogadores.values():
            if not j["ativo"] or len(j["mao"]) < 2:
                continue
            mao_treys = [Card.new(c) for c in j["mao"]]
            score = self.evaluator.evaluate(board_treys, mao_treys)
            classe = self.evaluator.class_to_string(
                self.evaluator.get_rank_class(score)
            )

            if score < melhor_score:
                melhor_score = score
                vencedores = [j]
                melhor_classe = classe
            elif score == melhor_score:
                vencedores.append(j)

        premio = self.pote / len(vencedores)
        for v in vencedores:
            v["saldo"] += premio

        nomes_vencedores = ", ".join(v["nome"] for v in vencedores)
        return self._gerar_estado_individualizado(
            f"{ultimo_aviso} SHOWDOWN: {nomes_vencedores} venceu R${premio:.0f} com {melhor_classe}!"
        )

    def _gerar_estado_individualizado(self, msg: str) -> list[tuple]:
        conns = self._conns_registradas()
        conn_da_vez = (
            conns[self.indice_turno]
            if conns
            and self.aguardando_cartas == 0
            and self.fase not in ("AGUARDANDO", "SHOWDOWN")
            else None
        )
        nome_da_vez = self.jogadores[conn_da_vez]["nome"] if conn_da_vez else "-"

        mensagens = []
        for conn, j in self.jogadores.items():
            a_pagar = max(0.0, self.aposta_atual - j["aposta_rodada"])
            dados = {
                "fase": self.fase,
                "pote": self.pote,
                "seu_saldo": j["saldo"],
                "a_pagar": a_pagar,
                "sua_vez": (conn == conn_da_vez),
                "jogador_vez": nome_da_vez,
                "msg": msg,
            }
            mensagens.append((conn, "estado_mesa", dados))
        return mensagens
