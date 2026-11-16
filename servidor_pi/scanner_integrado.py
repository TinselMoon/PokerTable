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
# Se no log aparecer "Carta removida" ao colocar a carta, troque para False
IR_ATIVO_EM_HIGH = False

# Pinos BCM livres fora do bloco 1-26 do LCD 3.5"
# (físicos: 37 -> GPIO 26, 35 -> GPIO 19, 33 -> GPIO 13)
PINO_LED = 26
PINO_VCC_IR = 19
PINO_DO_IR = 13

TEMPO_ESTABILIZACAO = 0.40
VOTOS_NECESSARIOS = 7

ROI_NUMERO = (179, 250, 79, 101)
ROI_NAIPE = (179, 352, 82, 86)

LIMIAR_PRESENCA = 120.0
LIMIAR_VERMELHO = 30.0
AREA_MIN = 15.0
LADO = 32

NOMES_VALORES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
NOMES_NAIPES_VERMELHOS = ["Copas", "Ouros"]
NOMES_NAIPES_PRETOS = ["Espadas", "Paus"]

MAPA_VALORES = {"10": "T", "A": "A", "J": "J", "Q": "Q", "K": "K"}
MAPA_NAIPES = {"Copas": "h", "Ouros": "d", "Espadas": "s", "Paus": "c"}

lock_estado = threading.Lock()
estado = {
    "quer_camera": False,
    "rodando": True,
    "cartas_usadas": set(),
    "resetar_leitura": False,
}

HOG_DESCRIPTOR = cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9)


def calcular_hog(img):
    return HOG_DESCRIPTOR.compute(img).reshape(1, -1)


def traduzir_codigo(valor: str, naipe: str) -> str:
    v = MAPA_VALORES.get(valor, valor)
    n = MAPA_NAIPES.get(naipe, "")
    return f"{v}{n}"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def evento(msg: str) -> None:
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
            log(
                f"Hardware GPIO inicializado (LED={pino_led}, VCC_IR={pino_vcc_ir}, DO_IR={pino_do_ir}, active_high={ativo_high})."
            )
        except Exception as e:
            log(f"Hardware GPIO indisponível ({e}); operando em fallback.")

    def ligar(self) -> None:
        if self.ativo:
            self.led.on()
            self.vcc_ir.on()
            time.sleep(0.10)

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


def extrair_simbolo(recorte):
    cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    brilho = cv2.mean(cinza)[0]
    if brilho < LIMIAR_PRESENCA:
        return None, brilho

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
        return None, brilho

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

    return (img_redim, vermelho), brilho


def prever(modelo, nomes, img) -> str:
    caracteristicas = np.float32(calcular_hog(img))
    _, r = modelo.predict(caracteristicas)
    i = int(r[0][0])
    return nomes[i] if 0 <= i < len(nomes) else "?"


def ler_comandos() -> None:
    for linha in sys.stdin:
        cmd = linha.strip()
        if not cmd:
            continue
        with lock_estado:
            if cmd == "LIGAR":
                estado["quer_camera"] = True
            elif cmd == "DESLIGAR":
                estado["quer_camera"] = False
            elif cmd == "RESET_LEITURA":
                estado["resetar_leitura"] = True
            elif cmd.startswith("USADAS;"):
                corpo = cmd.split(";", 1)[1].strip()
                estado["cartas_usadas"] = {
                    c.strip() for c in corpo.split(",") if c.strip()
                }
            elif cmd == "SAIR":
                estado["rodando"] = False
                break
            else:
                log(f"Comando desconhecido: {cmd}")
    with lock_estado:
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
    hw_ligado = False
    estado_ir_anterior = None
    momento_deteccao_ir = 0.0
    candidata_atual = None
    votos = 0
    votos_duplicada = 0
    carta_confirmada = False
    duplicada_notificada = None
    salvou_debug_carta = False
    ultimo_log_debug = 0.0

    rx, ry, rw, rh = ROI_NUMERO
    nx, ny, nw, nh = ROI_NAIPE

    try:
        while True:
            with lock_estado:
                rodando = estado["rodando"]
                quer_camera = estado["quer_camera"]
                cartas_usadas = set(estado["cartas_usadas"])
                resetar = estado["resetar_leitura"]
                if resetar:
                    estado["resetar_leitura"] = False

            if not rodando:
                break

            if resetar:
                candidata_atual = None
                votos = 0
                votos_duplicada = 0
                carta_confirmada = False
                duplicada_notificada = None
                salvou_debug_carta = False

            if quer_camera:
                if not hw_ligado:
                    hw.ligar()
                    hw_ligado = True
                    estado_ir_anterior = None
                    candidata_atual = None
                    votos = 0
                    votos_duplicada = 0
                    carta_confirmada = False
                    duplicada_notificada = None
                    salvou_debug_carta = False

                    if cap is None:
                        try:
                            from picamera2 import Picamera2

                            cap = Picamera2()
                            cap.configure(
                                cap.create_video_configuration(
                                    main={"size": (640, 480), "format": "RGB888"}
                                )
                            )
                            cap.start()
                            time.sleep(1.0)
                        except Exception as e:
                            hw.desligar()
                            hw_ligado = False
                            log(f"Falha ao ligar câmera: {e}")
                            evento(f"ERRO;Falha ao ligar câmera: {e}")
                            with lock_estado:
                                estado["quer_camera"] = False
                            time.sleep(0.5)
                            continue
                    else:
                        time.sleep(0.4)

                    evento("CAMERA_LIGADA")

            else:
                if hw_ligado:
                    hw.desligar()
                    hw_ligado = False
                    estado_ir_anterior = None
                    candidata_atual = None
                    votos = 0
                    votos_duplicada = 0
                    carta_confirmada = False
                    duplicada_notificada = None
                    evento("CAMERA_DESLIGADA")
                time.sleep(0.12)
                continue

            if cap is None:
                time.sleep(0.1)
                continue

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
                votos_duplicada = 0
                carta_confirmada = False
                duplicada_notificada = None
                salvou_debug_carta = False
                estado_ir_anterior = carta_presente

            if not carta_presente or carta_confirmada:
                time.sleep(0.03)
                continue

            if (time.monotonic() - momento_deteccao_ir) < TEMPO_ESTABILIZACAO:
                time.sleep(0.02)
                continue

            try:
                bruto = cap.capture_array("main")
            except Exception as e:
                log(f"ERRO ao capturar frame: {e}")
                time.sleep(0.05)
                continue

            frame = orientar(bruto)
            rec_num = frame[ry : ry + rh, rx : rx + rw]
            rec_nai = frame[ny : ny + nh, nx : nx + nw]

            res_v, brilho_v = extrair_simbolo(rec_num)
            res_n, brilho_n = extrair_simbolo(rec_nai)

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

            if not salvou_debug_carta:
                debug_img = frame.copy()
                cv2.rectangle(debug_img, (rx, ry), (rx + rw, ry + rh), (255, 0, 0), 2)
                cv2.rectangle(debug_img, (nx, ny), (nx + nw, ny + nh), (0, 0, 255), 2)
                cv2.putText(
                    debug_img,
                    f"{valor} de {naipe} | B:{brilho_v:.0f}/{brilho_n:.0f}",
                    (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imwrite("/tmp/debug_scanner.jpg", debug_img)
                salvou_debug_carta = True

            agora = time.monotonic()
            if (agora - ultimo_log_debug) >= 0.6:
                log(
                    f"[DEBUG] Leitura={valor} de {naipe} | votos={votos}/{VOTOS_NECESSARIOS} | "
                    f"brilho_num={brilho_v:.1f} brilho_naipe={brilho_n:.1f}"
                )
                ultimo_log_debug = agora

            if valor != "?" and naipe != "?":
                codigo = traduzir_codigo(valor, naipe)
                leitura = (valor, naipe)

                if codigo in cartas_usadas:
                    votos = 0
                    if leitura == candidata_atual:
                        votos_duplicada += 1
                    else:
                        candidata_atual = leitura
                        votos_duplicada = 1

                    if (
                        votos_duplicada >= VOTOS_NECESSARIOS
                        and duplicada_notificada != codigo
                    ):
                        duplicada_notificada = codigo
                        log(f"[SCANNER] Carta duplicada bloqueada: {valor} de {naipe}")
                        evento(f"DUPLICADA;{valor};{naipe}")
                else:
                    votos_duplicada = 0
                    duplicada_notificada = None
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
                votos_duplicada = 0

            time.sleep(0.03)
    finally:
        if cap is not None:
            cap.stop()
            cap.close()
        hw.fechar()


if __name__ == "__main__":
    main()
