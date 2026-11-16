import sys
import threading
import time
from pathlib import Path
import cv2
import numpy as np
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# Configurações de ROI (x, y, largura, altura) para recortes no frame já orientado
ROI_NUMERO = (179, 250, 79, 101)
ROI_NAIPE = (179, 352, 82, 86)

LIMIAR_PRESENCA = 120.0
LIMIAR_VERMELHO = 30.0
AREA_MIN = 15.0
LADO = 32

NOMES_VALORES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
NOMES_NAIPES_VERMELHOS = ["Copas", "Ouros"]
NOMES_NAIPES_PRETOS = ["Espadas", "Paus"]

estado = {"quer_camera": False, "rodando": True}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def evento(msg):
    print(msg, flush=True)


class HardwareScanner:
    def __init__(self, pino_led=17, pino_vcc_ir=27, pino_do_ir=22):
        self.ativo = False
        try:
            self.led = DigitalOutputDevice(pino_led, initial_value=False)
            self.vcc_ir = DigitalOutputDevice(pino_vcc_ir, initial_value=False)
            self.sensor_ir = DigitalInputDevice(pino_do_ir, pull_up=True)
            self.ativo = True
        except Exception as e:
            log(f"Hardware GPIO indisponível ({e}); seguindo sem LED/IR.")

    def ligar(self):
        if self.ativo:
            self.led.on()
            self.vcc_ir.on()
            time.sleep(0.05)  # Estabiliza o sensor IR

    def desligar(self):
        if self.ativo:
            self.led.off()
            self.vcc_ir.off()

    @property
    def carta_no_sensor(self) -> bool:
        if not self.ativo:
            return True  # Fallback caso rode sem GPIO conectado
        return not self.sensor_ir.is_active

    def fechar(self):
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


def prever(modelo, nomes, img):
    caracteristicas = np.float32(calcular_hog(img))
    _, r = modelo.predict(caracteristicas)
    i = int(r[0][0])
    return nomes[i] if 0 <= i < len(nomes) else "?"


def ler_comandos():
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
            raise FileNotFoundError("Arquivo XML vazio ou não encontrado.")
    except Exception as e:
        evento(f"ERRO;Falha ao carregar modelos XML: {e}")
        return 1

    hw = HardwareScanner(pino_led=17, pino_vcc_ir=27, pino_do_ir=22)

    threading.Thread(target=ler_comandos, daemon=True).start()
    evento("PRONTO")

    cap = None
    carta_em_leitura = False
    ultima, repeticoes = None, 0
    VOTOS_NECESSARIOS = 5

    try:
        while estado["rodando"]:
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
                carta_em_leitura, ultima, repeticoes = False, None, 0
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

            # 1. Verifica primeiro o sensor infravermelho físico
            if not hw.carta_no_sensor:
                if carta_em_leitura:
                    evento("CARTA_REMOVIDA")
                carta_em_leitura, ultima, repeticoes = False, None, 0
                time.sleep(0.05)
                continue

            # 2. Se já leu essa carta e ela continua parada no IR, aguarda ser retirada
            if carta_em_leitura:
                time.sleep(0.05)
                continue

            # 3. Carta presente no IR: captura frame e classifica
            try:
                bruto = cap.capture_array("main")
            except Exception as e:
                log(f"ERRO: Falha ao capturar frame: {e}")
                time.sleep(0.1)
                continue

            frame = orientar(bruto)
            rx, ry, rw, rh = ROI_NUMERO
            nx, ny, nw, nh = ROI_NAIPE
            rec_num = frame[ry : ry + rh, rx : rx + rw]
            rec_nai = frame[ny : ny + nh, nx : nx + nw]

            res_v = extrair_simbolo(rec_num)
            res_n = extrair_simbolo(rec_nai)
            valor = naipe = ""

            if res_v is not None:
                valor = prever(svm_valores, NOMES_VALORES, res_v[0])
            if res_n is not None:
                img_n, is_red = res_n
                naipe = (
                    prever(svm_vermelhos, NOMES_NAIPES_VERMELHOS, img_n)
                    if is_red
                    else prever(svm_pretos, NOMES_NAIPES_PRETOS, img_n)
                )

            if valor and naipe and valor != "?" and naipe != "?":
                leitura = (valor, naipe)
                repeticoes = repeticoes + 1 if leitura == ultima else 1
                ultima = leitura
                if repeticoes >= VOTOS_NECESSARIOS:
                    evento(f"CARTA;{valor};{naipe}")
                    carta_em_leitura = True
            else:
                ultima, repeticoes = None, 0

            time.sleep(0.05)
    finally:
        if cap is not None:
            cap.stop()
            cap.close()
        hw.fechar()


if __name__ == "__main__":
    main()
