import time
from pathlib import Path
import cv2
import numpy as np
from gpiozero import DigitalInputDevice, DigitalOutputDevice
from picamera2 import Picamera2

# ==============================================================================
# CONFIGURAÇÕES E CALIBRAÇÃO
# ==============================================================================
# Se o IR estiver indicando "CARTA" quando vazio e "VAZIO" com carta, mude para False
IR_ATIVO_EM_HIGH = True

# Pinos BCM (físicos: 11 -> GPIO 17, 13 -> GPIO 27, 15 -> GPIO 22)
PINO_LED = 17
PINO_VCC_IR = 27
PINO_DO_IR = 22

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


def main():
    print("=== INICIANDO TESTE DE HARDWARE E RECONHECIMENTO ===")

    # 1. Carregamento dos modelos SVM
    pasta_modelos = Path(__file__).resolve().parent / "modelos"
    try:
        svm_valores = cv2.ml.SVM_load(str(pasta_modelos / "modelo_valores.xml"))
        svm_vermelhos = cv2.ml.SVM_load(
            str(pasta_modelos / "modelo_naipes_vermelhos.xml")
        )
        svm_pretos = cv2.ml.SVM_load(str(pasta_modelos / "modelo_naipes_pretos.xml"))
        if svm_valores.empty() or svm_vermelhos.empty() or svm_pretos.empty():
            raise FileNotFoundError("Um ou mais arquivos XML estão vazios ou ausentes.")
        print("[OK] Modelos SVM carregados com sucesso.")
    except Exception as e:
        print(f"[ERRO] Falha ao carregar modelos XML: {e}")
        return

    # 2. Inicialização dos pinos GPIO (LED + IR)
    led = DigitalOutputDevice(PINO_LED, initial_value=False)
    vcc_ir = DigitalOutputDevice(PINO_VCC_IR, initial_value=False)
    sensor_ir = DigitalInputDevice(
        PINO_DO_IR, pull_up=None, active_state=IR_ATIVO_EM_HIGH
    )

    led.on()
    vcc_ir.on()
    time.sleep(0.1)
    print(f"[OK] LED (GPIO {PINO_LED}) e VCC do IR (GPIO {PINO_VCC_IR}) LIGADOS.")

    # 3. Inicialização da Câmera CSI
    cap = Picamera2()
    cap.configure(
        cap.create_video_configuration(main={"size": (640, 480), "format": "RGB888"})
    )
    cap.start()
    time.sleep(1.0)
    print("[OK] Câmera CSI iniciada.")
    print("\nControles na janela de vídeo:")
    print("  [Q] -> Sair do teste")
    print("  [I] -> Inverter lógica do sensor IR em tempo real\n")

    estado_ir_anterior = None
    ultima_carta_logada = None
    rx, ry, rw, rh = ROI_NUMERO
    nx, ny, nw, nh = ROI_NAIPE

    try:
        while True:
            # Leitura do sensor infravermelho
            carta_presente = sensor_ir.is_active

            # Loga somente quando o estado do sensor muda (para não poluir o terminal)
            if carta_presente != estado_ir_anterior:
                if carta_presente:
                    print(">>> [IR] CARTA DETECTADA NO SCANNER! Lendo imagem...")
                else:
                    print("--- [IR] Scanner vazio (carta removida).")
                    ultima_carta_logada = None
                estado_ir_anterior = carta_presente

            # Captura e orienta o frame da câmera
            bruto = cap.capture_array("main")
            frame = orientar(bruto)
            frame_debug = frame.copy()

            # Desenha os retângulos de ROI (Azul = Número, Vermelho = Naipe)
            cv2.rectangle(frame_debug, (rx, ry), (rx + rw, ry + rh), (255, 0, 0), 2)
            cv2.rectangle(frame_debug, (nx, ny), (nx + nw, ny + nh), (0, 0, 255), 2)

            texto_carta = "Aguardando IR..."
            cor_status = (0, 165, 255)  # Laranja

            if carta_presente:
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

                texto_carta = f"Leitura: {valor} de {naipe}"
                cor_status = (
                    (0, 255, 0) if (valor != "?" and naipe != "?") else (0, 255, 255)
                )

                # Loga no terminal sempre que identificar uma carta válida (ou mudar de carta)
                carta_atual = f"{valor} de {naipe}"
                if valor != "?" and naipe != "?" and carta_atual != ultima_carta_logada:
                    print(f"    [VISÃO] Carta identificada: {carta_atual}")
                    ultima_carta_logada = carta_atual

            # Escreve o status do IR e da leitura diretamente na janela de vídeo
            status_ir_txt = "IR: CARTA DETECTADA" if carta_presente else "IR: VAZIO"
            cv2.putText(
                frame_debug,
                status_ir_txt,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                cor_status,
                2,
            )
            cv2.putText(
                frame_debug,
                texto_carta,
                (15, 65),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                cor_status,
                2,
            )

            cv2.imshow("Teste Scanner - Camera, IR e SVM", frame_debug)

            tecla = cv2.waitKey(30) & 0xFF
            if tecla == ord("q"):
                break
            elif tecla == ord("i"):
                # Permite inverter a lógica do IR sem precisar fechar o script
                novo_estado = not sensor_ir.active_state
                sensor_ir.close()
                sensor_ir = DigitalInputDevice(
                    PINO_DO_IR, pull_up=None, active_state=novo_estado
                )
                estado_ir_anterior = None
                print(f"[CONFIG] Lógica do IR invertida (active_state={novo_estado})")

    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    finally:
        print("Desligando LED, IR e câmera...")
        cap.stop()
        cap.close()
        led.off()
        vcc_ir.off()
        led.close()
        vcc_ir.close()
        sensor_ir.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
