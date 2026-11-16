import sys
import threading
import time
from pathlib import Path
import cv2
import numpy as np
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ==============================================================================
# CONFIGURAÇÕES DE HARDWARE E CALIBRAÇÃO
# ==============================================================================
# Ajuste para False se o seu sensor IR operar em lógica invertida
<<<<<<< HEAD
IR_ATIVO_EM_HIGH = True
=======
IR_ATIVO_EM_HIGH = False
>>>>>>> Pokerbeta

# Pinos BCM (físicos: 11 -> GPIO 17, 13 -> GPIO 27, 15 -> GPIO 22)
PINO_LED = 17
PINO_VCC_IR = 27
PINO_DO_IR = 22

# Parâmetros de estabilidade e consenso de leitura
TEMPO_ESTABILIZACAO = 0.40  # Aguarda 400ms após o IR detectar antes de ler
VOTOS_NECESSARIOS = 7  # Quantos frames idênticos seguidos para confirmar

# Configurações de ROI (x, y, largura, altura) e visão computacional
ROI_NUMERO = (179, 250, 79, 101)
ROI_NAIPE = (179, 352, 82, 86)

LIMIAR_PRESENCA = 120.0
LIMIAR_VERMELHO = 30.0
AREA_MIN = 15.0
LADO = 32

NOMES_VALORES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
NOMES_NAIPES_VERMELHOS = ["Copas", "Ouros"]
NOMES_NAIPES_PRETOS = ["Espadas", "Paus"]

# Estado global compartilhado com a thread de comandos IPC
estado = {"quer_camera": False, "rodando": True}


def log(msg: str) -> None:
    # Logs de debug vão para STDERR para não interferir no IPC do STDOUT
    print(msg, file=sys.stderr, flush=True)


def evento(msg: str) -> None:
    # Eventos lidos pelo servidor_mesa.py vão para STDOUT
    print(msg, flush=True)


class HardwareScanner:
    def __init__(
        self, pino_led: int, pino_vcc_ir: int, pino_do_ir: int, ativo_high: bool
    ):
        self.ativo = False
        try:
            self.led = DigitalOutputDevice(pino_led, initial_value=False)
            self.vcc_ir = DigitalOutputDevice(pino_vcc_ir, initial_value=False)
            self.sensor_ir = DigitalInputDevice(
                pino_do_ir, pull_up=None, active_state=ativo_high
            )
            self.ativo = True
            log("Hardware GPIO inicializado (LED, VCC IR e DO IR).")
        except Exception as e:
            log(f"Hardware GPIO indisponível ({e}); operando em fallback.")

    def ligar(self) -> None:
        if self.ativo:
            self.led.on()
            self.vcc_ir.on()
            time.sleep(0.05)  # Pequena pausa para estabilizar o módulo IR

    def desligar(self) -> None:
        if self.ativo:
            self.led.off()
            self.vcc_ir.off()

    @property
    def carta_no_sensor(self) -> bool:
        if not self.ativo:
            return True
        return self.sensor_ir.is_active

    def fechar(self) -> None:
        if self.ativo:
            self.desligar()
            self.led.close()
            self.vcc_ir.close()
            self.sensor_ir.close()


def orientar(bruto):
    girado = cv2.rotate(bruto, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return cv2.flip(girado, 1)


def calcular_hog(img):
    hog = cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9)
    return hog.compute(img).reshape(1, -1)


def extrair_simbolo(recorte):
    cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    if cv2.mean(cinza)[0] < LIMIAR_PRESENCA:
        return None

    cinza_blur = cv2.GaussianBlur(cinza, (3, 3), 0)
    _, binaria = cv2.threshold(
        cinza_blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )

    contornos, _ = cv2.findContours(binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    area_max = 0.5 * recorte.size / 3
    x_min, y_min, x_max, y_max = 9999, 9999, -1, -1
    achou = False

    for c in contornos:
        a = cv2.contourArea(c)
        if a < AREA_MIN or a > area_max:
            continue
        x, y, w, h = cv2.boundingRect(c)
        x_min = min(x_min, x)
        y_min = min(y_min, y)
        x_max = max(x_max, x + w)
        y_max = max(y_max, y + h)
        achou = True

    if not achou:
        return None

    tinta = binaria[y_min:y_max, x_min:x_max]
    lado_sq = max(tinta.shape[1], tinta.shape[0])
    margem = max(2, lado_sq // 8)

    quadrado = np.zeros((lado_sq + 2 * margem, lado_sq + 2 * margem), dtype=np.uint8)
    ox = margem + (lado_sq - tinta.shape[1]) // 2
    oy = margem + (lado_sq - tinta.shape[0]) // 2
    quadrado[oy : oy + tinta.shape[0], ox : ox + tinta.shape[1]] = tinta

    img_redim = cv2.resize(quadrado, (LADO, LADO), interpolation=cv2.INTER_AREA)

    mascara = binaria[y_min:y_max, x_min:x_max]
    recorte_roi = recorte[y_min:y_max, x_min:x_max]
    media_bgr = cv2.mean(recorte_roi, mask=mascara)
    vermelho = (media_bgr[2] - 0.5 * (media_bgr[0] + media_bgr[1])) > LIMIAR_VERMELHO

    return img_redim, vermelho


def prever(modelo, nomes, img) -> str:
    caracteristicas = np.float32(calcular_hog(img))
    _, r = modelo.predict(caracteristicas)
    i = int(r[0][0])
    return nomes[i] if 0 <= i < len(nomes) else "?"


def ler_comandos() -> None:
    for linha in sys.stdin:
        cmd = linha.strip()
        if cmd == "LIGAR":
            estado["quer_camera"] = True
        elif cmd == "DESLIGAR":
            estado["quer_camera"] = False
        elif cmd == "SAIR":
            break
        elif cmd:
            log(f"Comando desconhecido: {cmd}")
    estado["rodando"] = False


def main():
    pasta_modelos = Path(__file__).resolve().parent / "modelos"
    try:
        svm_valores = cv2.ml.SVM_load(str(pasta_modelos / "modelo_valores.xml"))
        svm_vermelhos = cv2.ml.SVM_load(
            str(pasta_modelos / "modelo_naipes_vermelhos.xml")
        )
        svm_pretos = cv2.ml.SVM_load(str(pasta_modelos / "modelo_naipes_pretos.xml"))
        if svm_valores.empty() or svm_vermelhos.empty() or svm_pretos.empty():
            raise FileNotFoundError("Um ou mais arquivos XML estão vazios ou ausentes.")
    except Exception as e:
        evento(f"ERRO;Falha ao carregar modelos XML em {pasta_modelos}: {e}")
        return 1

    hw = HardwareScanner(PINO_LED, PINO_VCC_IR, PINO_DO_IR, IR_ATIVO_EM_HIGH)

    threading.Thread(target=ler_comandos, daemon=True).start()
    evento("PRONTO")

    cap = None
    estado_ir_anterior = None
    momento_deteccao_ir = 0.0
    candidata_atual = None
    votos = 0
    carta_confirmada = False

    rx, ry, rw, rh = ROI_NUMERO
    nx, ny, nw, nh = ROI_NAIPE

    try:
        while estado["rodando"]:
            # 1. Gerenciamento de estado da câmera CSI e alimentação do LED/IR
            if estado["quer_camera"] and cap is None:
                from picamera2 import Picamera2

                cap = Picamera2()
                cap.configure(
                    cap.create_video_configuration(
                        main={"size": (640, 480), "format": "RGB888"}
                    )
                )
                cap.start()
                time.sleep(1.0)
                hw.ligar()

                estado_ir_anterior = None
                candidata_atual = None
                votos = 0
                carta_confirmada = False
                evento("CAMERA_LIGADA")

            elif not estado["quer_camera"] and cap is not None:
                cap.stop()
                cap.close()
                cap = None
                hw.desligar()
                evento("CAMERA_DESLIGADA")

            if cap is None:
                time.sleep(0.1)
                continue

            # 2. Monitora bordas de subida/descida do sensor infravermelho
            carta_presente = hw.carta_no_sensor

            if carta_presente != estado_ir_anterior:
                if carta_presente:
                    momento_deteccao_ir = time.monotonic()
                    log("[IR] Carta entrou no scanner. Aguardando estabilizar...")
                else:
                    if estado_ir_anterior is not None:
                        log("[IR] Carta removida do scanner.")
                        evento("CARTA_REMOVIDA")
                candidata_atual = None
                votos = 0
                carta_confirmada = False
                estado_ir_anterior = carta_presente

            # 3. Se não há carta no IR ou ela já foi confirmada, aguarda sem processar SVM
            if not carta_presente or carta_confirmada:
                time.sleep(0.03)
                continue

            # 4. Aguarda o tempo de assentamento antes de iniciar a captura
            if (time.monotonic() - momento_deteccao_ir) < TEMPO_ESTABILIZACAO:
                time.sleep(0.02)
                continue

            # 5. Captura frame e executa classificação com votação
            try:
                bruto = cap.capture_array("main")
            except Exception as e:
                log(f"ERRO ao capturar frame: {e}")
                time.sleep(0.05)
                continue

            frame = orientar(bruto)
            rec_num = frame[ry : ry + rh, rx : rx + rw]
            rec_nai = frame[ny : ny + nh, nx : nx + nw]

            res_v = extrair_simbolo(rec_num)
            res_n = extrair_simbolo(rec_nai)

            valor = (
                prever(svm_valores, NOMES_VALORES, res_v[0])
                if res_v is not None
                else "?"
            )
            naipe = "?"
            if res_n is not None:
                img_n, is_red = res_n
                naipe = (
                    prever(svm_vermelhos, NOMES_NAIPES_VERMELHOS, img_n)
                    if is_red
                    else prever(svm_pretos, NOMES_NAIPES_PRETOS, img_n)
                )

            if valor != "?" and naipe != "?":
                leitura = (valor, naipe)
                if leitura == candidata_atual:
                    votos += 1
                else:
                    candidata_atual = leitura
                    votos = 1

                if votos >= VOTOS_NECESSARIOS:
                    carta_confirmada = True
                    log(f"[SCANNER] Carta confirmada: {valor} de {naipe}")
                    evento(f"CARTA;{valor};{naipe}")
            else:
                candidata_atual = None
                votos = 0

            time.sleep(0.03)
    finally:
        if cap is not None:
            cap.stop()
            cap.close()
        hw.fechar()


if __name__ == "__main__":
    main()
