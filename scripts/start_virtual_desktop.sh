#!/bin/bash
set -e

export DISPLAY=:99
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_TYPE=x11
export NO_AT_BRIDGE=0
export GTK_MODULES=gail:atk-bridge
export GNOME_ACCESSIBILITY=1

# Kill existing if any
pkill -f 'Xvfb :99' || true
pkill -f 'xfce4-session' || true
pkill -f 'x11vnc.*:99' || true
pkill -f 'websockify.*6080' || true
sleep 1

# Start Xvfb (1920x1080)
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 2

# D-Bus session
eval $(dbus-launch --sh-syntax)
export DBUS_SESSION_BUS_ADDRESS

# Enable accessibility
gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true

# Launch AT-SPI bus
for launcher in /usr/libexec/at-spi-bus-launcher /usr/lib/at-spi2-core/at-spi-bus-launcher; do
  if [ -x "$launcher" ]; then
    $launcher --launch-immediately &
    break
  fi
done
sleep 1

# Start XFCE4
xfce4-session &
sleep 3

# Start Read-Only x11vnc
nohup x11vnc -display :99 -forever -shared -rfbport 5900 -viewonly -nopw > /tmp/x11vnc.log 2>&1 &
sleep 1

# Start websockify for HTML5 browser viewing
nohup websockify --web /usr/share/novnc 6080 localhost:5900 > /tmp/websockify.log 2>&1 &

echo "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS" > /root/.vdisplay_env
echo "export DISPLAY=:99" >> /root/.vdisplay_env
echo "export DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS" >> /root/.vdisplay_env
echo "export NO_AT_BRIDGE=0" >> /root/.vdisplay_env
echo "export GTK_MODULES=gail:atk-bridge" >> /root/.vdisplay_env
