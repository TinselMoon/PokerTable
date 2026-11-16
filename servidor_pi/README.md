# Roteiro de Instalação: Tela Touch 3,5" ILI9486 + Interface Python (Raspberry Pi OS Lite)

Este guia documenta a instalação e configuração limpa de um display LCD 3,5" com driver **ILI9486** e toque resistivo (**ADS7846**) em um **Raspberry Pi 3 B+** rodando **Raspberry Pi OS Lite** (sem ambiente gráfico padrão), iniciando diretamente uma interface gráfica leve em Python (Tkinter) via Xorg mínimo.

---

## 1. Gravação do cartão SD e montagem

1. Use o **Raspberry Pi Imager** para gravar o **Raspberry Pi OS Lite** (Bookworm ou Trixie).
   * *Dica:* No Raspberry Pi 3 B+ (1 GB de RAM), a versão Lite 32-bit consome um pouco menos de memória, mas a 64-bit também funciona perfeitamente.
2. Antes de gravar, abra as **configurações personalizadas** no Imager e defina:
   * Hostname, usuário e senha.
   * Rede Wi-Fi (SSID, senha e país **BR**).
   * **SSH ativado** com autenticação por senha.
3. Com o Raspberry Pi desligado, encaixe a tela de 3,5" nos primeiros 26 pinos da GPIO, insira o cartão SD e ligue a alimentação (não é necessário monitor HDMI, teclado ou mouse).

---

## 2. Acesso SSH, atualização e autologin no console

Conecte-se ao Raspberry Pi a partir do seu computador:

```bash
ssh SEU_USUARIO@IP_DO_RASPBERRY
```

Atualize os pacotes do sistema:

```bash
sudo apt update && sudo apt upgrade -y
```

Configure o login automático no terminal local abrindo o utilitário de configuração:

```bash
sudo raspi-config
```

Dentro do menu:
1. Acesse **1 System Options → S5 Boot / Auto Login → B2 Console Autologin**.
2. Salve e saia **sem reiniciar ainda**.

---

## 3. Instalação do Xorg mínimo, drivers e Tkinter

Instale apenas o servidor Xorg mínimo, os drivers de vídeo (`fbdev`) e entrada (`libinput`), o Tkinter e o Git — sem puxar pacotes do ambiente de desktop:

```bash
sudo apt install --no-install-recommends -y \
  xserver-xorg xinit x11-xserver-utils \
  xserver-xorg-video-fbdev xserver-xorg-input-libinput \
  python3-tk git
```

---

## 4. Instalação manual dos arquivos do LCD-show

Clone o repositório **LCD-show** e copie apenas o overlay do display (`tft35a-overlay.dtb`) e a matriz de calibração do touch para rotação de 90° (`40-libinput.conf-90`). **Não** execute o script `./LCD35-show`, pois ele espera o gerenciador LightDM da versão Desktop.

```bash
cd ~
git clone https://github.com/goodtft/LCD-show.git
sudo cp ~/LCD-show/usr/tft35a-overlay.dtb /boot/firmware/overlays/tft35a.dtbo
sudo cp ~/LCD-show/usr/40-libinput.conf-90 /usr/share/X11/xorg.conf.d/40-libinput.conf
```

> **Nota sobre rotação:** Caso precise girar a tela futuramente, ajuste o valor `rotate=` no passo 5 e copie o arquivo correspondente de `~/LCD-show/usr/40-libinput.conf-{0,90,180,270}`.

---

## 5. Configuração do boot (`/boot/firmware/config.txt`)

Abra o arquivo de configuração do boot:

```bash
sudo nano /boot/firmware/config.txt
```

Faça apenas estes dois ajustes:
1. Localize a linha `dtoverlay=vc4-kms-v3d` e comente-a colocando um `#` no início:
   ```ini
   #dtoverlay=vc4-kms-v3d
   ```
2. No final do arquivo, abaixo da seção `[all]`, adicione:
   ```ini
   dtparam=spi=on
   dtoverlay=tft35a:rotate=90
   ```

Salve com **Ctrl+O**, **Enter** e saia com **Ctrl+X**.

> Não é necessário adicionar configurações de HDMI forçado nem modificar o arquivo `/boot/firmware/cmdline.txt`.

---

## 6. Permissões de vídeo/touch e configuração do Xorg

Crie a regra do `udev` para dar permissão de escrita ao grupo `video` no framebuffer do driver `fb_ili9486`, adicione o usuário atual aos grupos `video` e `input`, e crie o arquivo `99-fbdev.conf` sem fixar um caminho de `/dev/fbX` (o caminho real será resolvido automaticamente no boot):

```bash
echo 'SUBSYSTEM=="graphics", KERNEL=="fb*", ATTR{name}=="fb_ili9486", GROUP="video", MODE="0660"' | sudo tee /etc/udev/rules.d/99-ili9486.rules

sudo usermod -aG video,input "$USER"

cat << 'EOF' | sudo tee /usr/share/X11/xorg.conf.d/99-fbdev.conf
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

---

## 7. Script da interface Python e permissão de desligamento

Libere o comando `/usr/sbin/shutdown` sem senha no `sudoers` para que o botão de desligar da interface funcione sem travar:

```bash
echo "$USER ALL=(ALL) NOPASSWD: /usr/sbin/shutdown" | sudo tee /etc/sudoers.d/gui-shutdown
sudo chmod 440 /etc/sudoers.d/gui-shutdown
```

Crie o arquivo `~/interface.py`:

```bash
nano ~/interface.py
```

Cole o script abaixo:

```python
#!/usr/bin/env python3
import subprocess
import tkinter as tk
from datetime import datetime


class InterfaceLCD:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Painel LCD")

        # Fixa na resolução nativa 480x320 no canto superior esquerdo sem cursor
        self.root.geometry("480x320+0+0")
        self.root.configure(bg="#121212", cursor="none")
        self.root.resizable(False, False)

        # Atalho de saída caso conecte um teclado em testes futuros
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self._criar_tela_principal()
        self._criar_tela_confirmacao()
        self._atualizar_relogio()

    def _criar_tela_principal(self) -> None:
        self.frame_principal = tk.Frame(self.root, bg="#121212")
        self.frame_principal.place(x=0, y=0, width=480, height=320)

        header = tk.Frame(self.frame_principal, bg="#1E1E1E", height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        self.lbl_status = tk.Label(
            header,
            text="● Sistema Ativo",
            fg="#4CAF50",
            bg="#1E1E1E",
            font=("DejaVu Sans", 13, "bold"),
        )
        self.lbl_status.pack(side="left", padx=15)

        self.lbl_relogio = tk.Label(
            header,
            text="",
            fg="#E0E0E0",
            bg="#1E1E1E",
            font=("DejaVu Sans", 13),
        )
        self.lbl_relogio.pack(side="right", padx=15)

        corpo = tk.Frame(self.frame_principal, bg="#121212")
        corpo.pack(expand=True, fill="both", padx=20, pady=15)

        self.lbl_info = tk.Label(
            corpo,
            text="Interface pronta.\nToque no botão abaixo para testar.",
            fg="#FFFFFF",
            bg="#121212",
            font=("DejaVu Sans", 14),
            wraplength=430,
            justify="center",
        )
        self.lbl_info.pack(expand=True)

        tk.Button(
            corpo,
            text="Testar Toque",
            command=self._acao_teste,
            bg="#1976D2",
            fg="#FFFFFF",
            activebackground="#1565C0",
            activeforeground="#FFFFFF",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=2,
        ).pack(fill="x", pady=(0, 10))

        tk.Button(
            corpo,
            text="Desligar Raspberry Pi",
            command=self._mostrar_confirmacao,
            bg="#C62828",
            fg="#FFFFFF",
            activebackground="#8E0000",
            activeforeground="#FFFFFF",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=2,
        ).pack(fill="x")

    def _criar_tela_confirmacao(self) -> None:
        self.frame_confirmacao = tk.Frame(self.root, bg="#1A1A1A")

        tk.Label(
            self.frame_confirmacao,
            text="Deseja realmente desligar\no Raspberry Pi?",
            fg="#FFFFFF",
            bg="#1A1A1A",
            font=("DejaVu Sans", 16, "bold"),
            justify="center",
        ).pack(expand=True, pady=(30, 10))

        botoes = tk.Frame(self.frame_confirmacao, bg="#1A1A1A")
        botoes.pack(fill="x", padx=25, pady=(0, 35))

        tk.Button(
            botoes,
            text="Cancelar",
            command=self._ocultar_confirmacao,
            bg="#424242",
            fg="#FFFFFF",
            activebackground="#616161",
            activeforeground="#FFFFFF",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=3,
        ).pack(side="left", expand=True, fill="x", padx=(0, 10))

        tk.Button(
            botoes,
            text="Confirmar",
            command=self._desligar_sistema,
            bg="#C62828",
            fg="#FFFFFF",
            activebackground="#8E0000",
            activeforeground="#FFFFFF",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=3,
        ).pack(side="right", expand=True, fill="x", padx=(10, 0))

    def _acao_teste(self) -> None:
        self.lbl_info.config(text=f"Toque registrado às {datetime.now():%H:%M:%S}")

    def _mostrar_confirmacao(self) -> None:
        self.frame_confirmacao.place(x=0, y=0, width=480, height=320)
        self.frame_confirmacao.tkraise()

    def _ocultar_confirmacao(self) -> None:
        self.frame_confirmacao.place_forget()

    def _desligar_sistema(self) -> None:
        self.frame_confirmacao.place_forget()
        self.lbl_status.config(text="● Desligando...", fg="#FF9800")
        self.lbl_info.config(
            text="Encerrando o sistema com segurança.\nAguarde o LED verde apagar."
        )
        self.root.update()
        self.root.after(
            300,
            lambda: subprocess.run(
                ["sudo", "/usr/sbin/shutdown", "-h", "now"], check=False
            ),
        )

    def _atualizar_relogio(self) -> None:
        self.lbl_relogio.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._atualizar_relogio)


if __name__ == "__main__":
    root = tk.Tk()
    app = InterfaceLCD(root)
    root.mainloop()
```

Salve o arquivo (**Ctrl+O**, **Enter**, **Ctrl+X**) e dê permissão de execução:

```bash
chmod +x ~/interface.py
```

---

## 8. Autostart com detecção automática do framebuffer

Crie o arquivo `~/.xinitrc` para desativar o descanso de tela e abrir diretamente o script Python:

```bash
cat << EOF > ~/.xinitrc
#!/bin/sh
xset s off
xset -dpms
xset s noblank
exec /usr/bin/python3 "$HOME/interface.py"
EOF
chmod +x ~/.xinitrc
```

Adicione o bloco abaixo ao final do arquivo `~/.profile`. Ele aguarda até 15 segundos pelo carregamento do módulo SPI, identifica dinamicamente qual dispositivo real (`/dev/fb0`, `/dev/fb1` ou `/dev/fb2`) corresponde ao `fb_ili9486` e sobe o servidor gráfico exclusivamente no terminal local (`tty1`), sem interferir nas conexões SSH:

```bash
cat << 'EOF' >> ~/.profile

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
    exec startx -- -nocursor
fi
EOF
```

> *Opcional (auto-recuperação):* Se quiser que a interface reabra automaticamente caso o script Python feche por algum erro inesperado, substitua a última linha do `~/.xinitrc` por:
> ```sh
> while true; do
>     /usr/bin/python3 "$HOME/interface.py"
>     sleep 1
> done
> ```

---

## 9. Reinicialização e comandos úteis de manutenção

Reinicie o Raspberry Pi para aplicar todas as alterações:

```bash
sudo reboot
```

### Comandos úteis no dia a dia (via SSH)

| Objetivo | Comando |
| :--- | :--- |
| **Recarregar a interface após editar o `interface.py`** | `sudo systemctl restart getty@tty1` |
| **Ver qual `/dev/fbX` pertence ao LCD** | `grep -H . /sys/class/graphics/fb*/name` |
| **Testar o hardware do LCD direto no framebuffer** | `sudo dd if=/dev/urandom of=/dev/fb1 bs=1024 count=300` *(ajuste `fb1` conforme o comando acima)* |
| **Inspecionar erros do Xorg** | `grep -iE "EE\|WW\|fbdev" ~/.local/share/xorg/Xorg.0.log` |
| **Verificar carregamento do driver e touch no kernel** | `dmesg \| grep -iE "ili9486\|ads7846\|tft35a"` |