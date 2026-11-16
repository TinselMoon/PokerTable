# Roteiro Completo de Instalação — PokerTable (Raspberry Pi 3 B+)

Este guia descreve todo o processo para configurar um **Raspberry Pi 3 B+ virgem** com **Raspberry Pi OS Lite (64-bit)**, **display touch LCD 3,5" SPI (ILI9486)**, **câmera CSI real**, **LED/sensor IR**, **ambiente virtual Python (`.venv`)**, **inicialização automática** e **Hotspot Wi-Fi próprio** para rodar o sistema **PokerTable** em produção (sem simulação).

---

## 1. Requisitos e Ligações de Hardware

### Lista de componentes
* Raspberry Pi 3 B+ com cartão microSD (mínimo 16 GB, Classe 10/A1).
* Fonte de alimentação confiável de **5V / 2,5A** (ou superior).
* Display LCD 3,5" SPI com touch resistivo (`fb_ili9486` + `ADS7846`, resolução `480x320`).
* Câmera CSI conectada à porta `CAMERA` da placa.
* Circuito do scanner de cartas (LED de iluminação + módulo sensor infravermelho).

### Mapeamento dos pinos GPIO do scanner (`scanner_integrado.py`)

| Componente | GPIO (BCM) | Pino Físico | Observação |
| :--- | :---: | :---: | :--- |
| LED de iluminação | `GPIO 17` | Pino 11 | Controlado via `DigitalOutputDevice` |
| Alimentação VCC do IR | `GPIO 27` | Pino 13 | Ligado apenas durante o escaneamento |
| Sinal Digital (DO) do IR | `GPIO 22` | Pino 15 | Configurado com `IR_ATIVO_EM_HIGH = False` |

> **Atenção:** Conecte a câmera CSI e os pinos do scanner com o Raspberry Pi **totalmente desligado da energia**. Caso o seu display LCD 3,5" ocupe os primeiros 26 pinos do conector GPIO, verifique no esquema da placa do display se há conflito com o pino 11 (`GPIO 17`, frequentemente usado como `T_IRQ` em alguns modelos) e utilize um expansor/splitter GPIO ou remapeie `PINO_LED` em `scanner_integrado.py` se necessário.

---

## 2. Gravação do Sistema Operacional

1. No computador, abra o **Raspberry Pi Imager**.
2. Em **Dispositivo**, selecione **Raspberry Pi 3**.
3. Em **Sistema Operacional**, selecione **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)**.
4. Em **Armazenamento**, selecione o cartão microSD.
5. Clique em **Próximo** e escolha **Editar configurações** (Personalização do SO):
   * **Hostname:** `pokertable` (opcional).
   * **Usuário e senha:** defina um usuário padrão (ex.: `pi` ou seu nome) e uma senha.
   * **Rede Wi-Fi:** configure o Wi-Fi da sua casa **temporariamente** (necessário para baixar pacotes da internet) e defina o país do Wi-Fi como **`BR`**.
   * **Localidade:** fuso horário `America/Sao_Paulo`.
   * **Aba Serviços:** ative **SSH** com autenticação por senha.
6. Grave o cartão, insira no Raspberry Pi 3 B+ e ligue a placa.

---

## 3. Acesso Inicial, Autologin e Permissões

Aguarde cerca de 1 minuto para o primeiro boot e conecte via SSH pelo terminal do seu computador:

```bash
ssh SEU_USUARIO@IP_DO_PI
```

### 3.1. Ativar Console Autologin no `tty1`
Execute o configurador do sistema:

```bash
sudo raspi-config
```

Navegue até:
* **1 System Options** → **S5 Boot / Auto Login** → **B2 Console Autologin**

Selecione **Finish**, mas escolha **Não** quando perguntar se deseja reiniciar agora.

### 3.2. Configurar grupos de hardware e permissão de desligamento
Adicione o usuário atual aos grupos de vídeo, entrada (touch) e GPIO, e libere o comando `shutdown` sem senha para que o botão `⏻` da interface possa desligar o Raspberry Pi com segurança:

```bash
sudo usermod -aG video,input,gpio "$USER"
echo "$USER ALL=(ALL) NOPASSWD: /usr/sbin/shutdown" | sudo tee /etc/sudoers.d/gui-shutdown
sudo chmod 440 /etc/sudoers.d/gui-shutdown
```

**Verificação:**
```bash
sudo visudo -c
```
A saída deve mostrar `parsed OK` para `/etc/sudoers.d/gui-shutdown`.

---

## 4. Instalação de Todas as Dependências do Sistema

Instalar **OpenCV**, **NumPy**, **Picamera2**, **gpiozero** e **Tkinter** diretamente pelos repositórios `apt` evita compilações demoradas e poupa memória RAM no Raspberry Pi 3 B+.

Execute:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install --no-install-recommends -y \
  xserver-xorg xinit x11-xserver-utils \
  xserver-xorg-video-fbdev xserver-xorg-input-libinput \
  python3-tk python3-venv python3-pip git \
  python3-opencv python3-numpy python3-picamera2 python3-gpiozero \
  dnsmasq-base
```

> **Importante:** Instale apenas `dnsmasq-base` (necessário para o Hotspot do NetworkManager distribuir IPs). **Não** instale o pacote `dnsmasq` completo, pois o serviço dele conflita com a porta 53 do NetworkManager.

**Verificação dos pacotes instalados:**
```bash
python3 -c "import tkinter, cv2, numpy, picamera2, gpiozero; print('DEPENDENCIAS SISTEMA OK')"
```
Deve imprimir `DEPENDENCIAS SISTEMA OK` sem erros.

---

## 5. Configuração do Display LCD 3,5" (ILI9486 + Touch)

> **Aviso:** **Não execute** o script automático `./LCD35-show` do repositório `LCD-show`, pois ele foi feito para versões antigas do Raspberry Pi OS Desktop e quebra a configuração de boot e vídeo no OS Lite 64-bit. Copie manualmente apenas os dois arquivos necessários abaixo.

### 5.1. Copiar o overlay do display e a calibração do touch
```bash
git clone https://github.com/goodtft/LCD-show.git /tmp/LCD-show
sudo cp /tmp/LCD-show/usr/tft35a-overlay.dtb /boot/firmware/overlays/tft35a.dtbo
sudo cp /tmp/LCD-show/usr/40-libinput.conf-90 /usr/share/X11/xorg.conf.d/40-libinput.conf
rm -rf /tmp/LCD-show
```

**Verificação:**
```bash
ls -l /boot/firmware/overlays/tft35a.dtbo /usr/share/X11/xorg.conf.d/40-libinput.conf
```

### 5.2. Editar `/boot/firmware/config.txt`
Abra o arquivo de boot:

```bash
sudo nano /boot/firmware/config.txt
```

Faça os seguintes ajustes:
1. Localize a linha `dtoverlay=vc4-kms-v3d` e comente-a colocando um `#` no início:
   ```ini
   #dtoverlay=vc4-kms-v3d
   ```
2. Confirme que `camera_auto_detect=1` permanece **descomentado** para que a câmera CSI seja detectada automaticamente.
3. No final do arquivo (dentro da seção `[all]`), adicione:
   ```ini
   dtparam=spi=on
   dtoverlay=tft35a:rotate=90
   ```

Salve e feche (`Ctrl + O`, `Enter`, `Ctrl + X`).

### 5.3. Criar regra `udev` e configuração mínima do Xorg
Deixe o framebuffer livre no Xorg para que seja detectado dinamicamente no momento do boot (evitando falhas caso o dispositivo mude entre `fb0` e `fb1`):

```bash
echo 'SUBSYSTEM=="graphics", KERNEL=="fb*", ATTR{name}=="fb_ili9486", GROUP="video", MODE="0660"' | sudo tee /etc/udev/rules.d/99-ili9486.rules

sudo tee /usr/share/X11/xorg.conf.d/99-fbdev.conf > /dev/null <<'EOF'
Section "Device"
    Identifier "LCD"
    Driver "fbdev"
EndSection

Section "Screen"
    Identifier "LCDScreen"
    Device "LCD"
    DefaultDepth 16
EndSection
EOF
```

### 5.4. Reiniciar e validar LCD + Câmera CSI
```bash
sudo reboot
```

Após reconectar via SSH, valide os dois hardwares:

```bash
grep -H fb_ili9486 /sys/class/graphics/fb*/name
rpicam-hello --list-cameras
```

**Resultado esperado:**
* O primeiro comando retorna algo como `/sys/class/graphics/fb1/name:fb_ili9486` (ou `fb0`).
* O segundo comando lista o sensor da sua câmera CSI (ex.: `ov5647` ou `imx219`) com os modos suportados.

---

## 6. Instalação do Projeto e Criação do Ambiente Virtual (`.venv`)

### 6.1. Colocar os arquivos do projeto na pasta `~/PokerTable`
Clone seu repositório (ou transfira via `scp`) para a pasta inicial do usuário, garantindo a seguinte estrutura em `~/PokerTable/servidor_pi`:

```text
~/PokerTable/
└── servidor_pi/
    ├── interface.py
    ├── servidor_mesa.py
    ├── regras_de_negocio.py
    ├── protocolo.py
    ├── scanner_integrado.py
    ├── pyproject.toml
    └── modelos/
        ├── modelo_valores.xml
        ├── modelo_naipes_vermelhos.xml
        └── modelo_naipes_pretos.xml
```

> **Checklist rápido dos arquivos de produção:**
> * Em `servidor_pi/servidor_mesa.py`, confirme que `obter_ip_local()` utiliza `hostname -I` para exibir corretamente `192.168.4.1` mesmo sem internet.
> * Em `servidor_pi/scanner_integrado.py`, confirme que não há marcadores de conflito do Git e que `IR_ATIVO_EM_HIGH = False` está configurado conforme seu sensor IR.
> * Em `servidor_pi/interface.py`, confirme que `ScrollableTouchFrame` tem `width=1, height=1` no `tk.Canvas` e que os rodapés do Lobby, Showdown e Placar são empacotados com `side="bottom"` antes da área rolável.

### 6.2. Criar o ambiente virtual `.venv` com acesso aos pacotes do sistema
O parâmetro `--system-site-packages` é essencial: ele permite que a `.venv` enxergue o `cv2`, `picamera2`, `gpiozero` e `numpy` instalados pelo `apt`, isolando apenas a biblioteca `treys`:

```bash
cd ~/PokerTable/servidor_pi
rm -rf .venv
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install treys
```

*(Alternativa: se preferir gerenciar com `uv`, instale com `curl -LsSf https://astral.sh/uv/install.sh | sh` e rode `uv sync` dentro de `~/PokerTable/servidor_pi`, já que o `pyproject.toml` contém `system-site-packages = true`.)*

### 6.3. Validar todas as importações na `.venv`
```bash
~/PokerTable/servidor_pi/.venv/bin/python -c "import tkinter, cv2, numpy, picamera2, gpiozero, treys; print('AMBIENTE VENV 100% OK')"
```

**Verificação:** Deve imprimir `AMBIENTE VENV 100% OK` sem erros.

---

## 7. Inicialização Automática da Interface no Display LCD

Nesta etapa configuramos o Xorg mínimo para subir direto no `tty1` no boot e abrir o `interface.py` em **modo real** (sem `--simulador` e sem `--mouse`), mantendo o terminal SSH livre para manutenção.

### 7.1. Criar o `~/.xinitrc` de produção
```bash
cat <<'EOF' > ~/.xinitrc
#!/bin/sh
xset s off
xset -dpms
xset s noblank
cd "$HOME/PokerTable/servidor_pi" || exit 1
exec "$HOME/PokerTable/servidor_pi/.venv/bin/python" interface.py >> "$HOME/poker_boot.log" 2>&1
EOF
chmod +x ~/.xinitrc
```

### 7.2. Garantir leitura do `~/.profile` e adicionar autostart do Xorg
Remova qualquer `~/.bash_profile` (se existir, ele impede o Bash de ler o `~/.profile`):

```bash
rm -f ~/.bash_profile
```

Adicione o bloco de detecção dinâmica do framebuffer `fb_ili9486` ao final do `~/.profile`:

```bash
cat <<'EOF' >> ~/.profile

if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    for i in $(seq 1 15); do
        for f in /sys/class/graphics/fb*/name; do
            if [ "$(cat "$f" 2>/dev/null)" = "fb_ili9486" ]; then
                export FRAMEBUFFER="/dev/$(basename "$(dirname "$f")")"
                break 2
            fi
        done
        sleep 1
    done
    exec startx -- -nocursor >> "$HOME/xorg_boot.log" 2>&1
fi
EOF
```

### 7.3. Testar a inicialização antes do Hotspot
Recarregue apenas o terminal local via SSH:

```bash
sudo systemctl restart getty@tty1
```

**Verificação:**
* Em até 10 segundos a tela **LOBBY** do PokerTable deve aparecer no LCD 3,5" com o IP atual na porta `5000`, botões de blinds (`-`/`+`), `Bot Teste: OFF`, `INICIAR PARTIDA` e o ícone `⏻` no canto superior direito.
* Confirme via SSH que o scanner real (não o simulador) subiu junto:
  ```bash
  pgrep -af scanner_integrado.py
  ```

---

## 8. Configuração do Hotspot Wi-Fi Próprio (`PokerTable`)

Esta etapa transforma o Raspberry Pi em um ponto de acesso Wi-Fi offline com IP fixo **`192.168.4.1`**, permitindo conectar os celulares Android em qualquer lugar sem roteador externo.

> **Atenção:** Ao ativar o perfil `PokerAP` na interface `wlan0`, sua conexão SSH atual pelo Wi-Fi da casa será encerrada. Para acessar por SSH novamente, conecte o seu computador na rede Wi-Fi **`PokerTable`** e conecte em `ssh SEU_USUARIO@192.168.4.1`.

### 8.1. Liberar rádio Wi-Fi para o Brasil
```bash
sudo raspi-config nonint do_wifi_country BR
sudo rfkill unblock wifi
```

### 8.2. Criar o perfil persistente de Ponto de Acesso (NetworkManager)
Substitua `"poker1234"` por outra senha (mínimo 8 caracteres), se desejar:

```bash
sudo nmcli con add type wifi ifname wlan0 mode ap con-name PokerAP ssid PokerTable autoconnect yes
sudo nmcli con modify PokerAP 802-11-wireless.band bg 802-11-wireless.channel 6
sudo nmcli con modify PokerAP wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.psk "poker1234"
sudo nmcli con modify PokerAP ipv4.method shared ipv4.addresses 192.168.4.1/24
sudo nmcli con modify PokerAP connection.autoconnect-priority 100
```

**Verificação antes de ativar:**
```bash
nmcli con show PokerAP | grep -E "mode|ssid|method|addresses|autoconnect"
```
Confirme `mode: ap`, `ipv4.method: shared` e `ipv4.addresses: 192.168.4.1/24`.

### 8.3. Ativar o Hotspot e reiniciar o Raspberry Pi
```bash
sudo nmcli con up PokerAP
```

*(A sessão SSH cairá.)* Conecte seu computador na rede Wi-Fi **PokerTable**, acesse `ssh SEU_USUARIO@192.168.4.1` e faça um reboot completo para validar a subida automática de ponta a ponta:

```bash
sudo reboot
```

### Como voltar ao Wi-Fi da casa quando precisar de internet
Conectado via SSH na rede `PokerTable` (`192.168.4.1`), liste os perfis salvos e troque temporariamente:

```bash
nmcli con show
sudo nmcli con down PokerAP && sudo nmcli con up "NOME_DO_SEU_WIFI"
```
No próximo reinício, por ter prioridade `100`, o Raspberry Pi voltará automaticamente ao modo Hotspot `PokerTable`.

---

## 9. Validação Final em Produção

Após o reboot completo (sem nenhum cabo HDMI ou teclado conectado):

1. **Display LCD:** Deve abrir sozinho na tela de Lobby exibindo **`LOBBY • 192.168.4.1:5000`**.
2. **Conexão Android:** Conecte os celulares na rede Wi-Fi **`PokerTable`** (toque em *Manter conectado* se o Android avisar *Sem acesso à internet*), abra o app **PokerTable**, informe o IP **`192.168.4.1`** e porta **`5000`**, digite nome e saldo inicial e toque em **Entrar na Mesa**.
3. **Ordem e Blinds:** Teste os botões `-`/`+` dos blinds e `▲`/`▼` para ordenar os jogadores fisicamente na mesa.
4. **Câmera Real, LED e Sensor IR:** Toque em **INICIAR PARTIDA**:
   * O LED interno do scanner deve acender automaticamente.
   * Ao encostar uma carta no sensor IR, aguarde ~0,4s até o contador subir (`1 / 2 cartas lidas`).
   * Tente passar a mesma carta novamente para confirmar o bloqueio de duplicata.
   * Clique em **Confirmar Entrega** — apenas o celular daquele jogador recebe as 2 cartas.
   * Passe as 5 cartas da mesa (viradas para baixo) e clique em **Confirmar 5 Cartas** — o LED deve apagar automaticamente e o Pré-Flop inicia com os blinds cobrados.
5. **Desligamento Seguro:** Toque no botão `⏻` no canto superior direito do LCD e confirme. O scanner desliga LED/IR/câmera e o sistema faz o shutdown limpo (aguarde o LED verde da placa apagar antes de retirar da tomada).

---

## 10. Diagnóstico Rápido (Troubleshooting)

Caso algo não funcione como esperado, conecte via SSH (`ssh SEU_USUARIO@192.168.4.1`) e verifique:

* **Interface não abriu no LCD:**
  ```bash
  cat ~/poker_boot.log
  cat ~/xorg_boot.log
  ```
* **Reiniciar apenas a interface gráfica sem reiniciar o Raspberry Pi:**
  ```bash
  sudo systemctl restart getty@tty1
  ```
* **Câmera dá erro de alocação de memória (CMA) no Raspberry Pi 3 B+:**
  Sem o driver KMS, o kernel pode reservar menos memória CMA. Edite `sudo nano /boot/firmware/cmdline.txt` e adicione `cma=128M` no final da **mesma linha** (separado por um espaço), salve e reinicie.
* **Sensor IR lendo invertido (indica carta quando está vazio):**
  Altere `IR_ATIVO_EM_HIGH = True` em `~/PokerTable/servidor_pi/scanner_integrado.py` e reinicie a interface com `sudo systemctl restart getty@tty1`.
* **Touch invertido ou desalinhado:**
  Verifique se o arquivo `/usr/share/X11/xorg.conf.d/40-libinput.conf` foi copiado da variante `-90` (correspondente ao `dtoverlay=tft35a:rotate=90` no `config.txt`).