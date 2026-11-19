#!/usr/bin/env bash
set -Eeuo pipefail

fail() { printf '%s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'EOF'
Usage: sudo bash install-nginx.sh --ip PUBLIC_IPV4 --email EMAIL [--port 8088] [--yes]
       bash install-nginx.sh --ip PUBLIC_IPV4 [--port 8088] --check

Ubuntu/Debian with systemd and Snap. Run on the bot's machine, outside containers.
TCP 80 and 443 must reach this machine. The bot must listen on 127.0.0.1:PORT.
--check validates input and prints nginx configuration without changing the machine.
--yes accepts installation and Let's Encrypt's subscriber agreement without prompting.
EOF
}

viewer_ip=''
viewer_email=''
viewer_port=8088
viewer_check=false
viewer_yes=false
while (($#)); do
    case "$1" in
        --ip|--email|--port)
            (($# >= 2)) || fail "Missing value for $1"
            case "$1" in
                --ip) viewer_ip=$2 ;;
                --email) viewer_email=$2 ;;
                --port) viewer_port=$2 ;;
            esac
            shift 2 ;;
        --check) viewer_check=true; shift ;;
        --yes) viewer_yes=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; fail "Unknown argument: $1" ;;
    esac
done
command -v python3 >/dev/null || fail 'Install python3 first.'
python3 - "$viewer_ip" "$viewer_port" <<'PY'
import ipaddress
import sys
try:
    address = ipaddress.IPv4Address(sys.argv[1])
    if not address.is_global or address.is_multicast:
        raise ValueError('Use a publicly routable IPv4 address belonging to this server.')
    port = sys.argv[2]
    if not port.isascii() or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise ValueError('Viewer port must be an integer between 1024 and 65535.')
    if port != str(int(port)):
        raise ValueError('Enter the port without leading zeroes.')
except ValueError as exc:
    sys.exit(str(exc))
PY

render_http() {
    cat <<EOF
server {
    listen 80;
    server_name ${viewer_ip};
    access_log off;
    location /.well-known/acme-challenge/ {
        root /var/www/modmailerviewer-acme;
    }
    location / { return 404; }
}
EOF
}
render_https() {
    cat <<EOF
server {
    listen 443 ssl;
    server_name ${viewer_ip};
    ssl_certificate /etc/letsencrypt/live/modmailerviewer-ip/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/modmailerviewer-ip/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:${viewer_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
}
if "$viewer_check"; then
    render_http
    render_https
    exit 0
fi
[[ $EUID == 0 ]] || fail 'Run the installer with sudo.'
[[ -f /etc/debian_version ]] || fail 'This installer supports Ubuntu/Debian only.'
[[ -d /run/systemd/system ]] || fail 'A running systemd host is required. Containers are not supported.'
[[ "$viewer_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || fail 'Supply a valid contact email with --email.'
viewer_site=/etc/nginx/sites-available/modmailerviewer-ip
viewer_link=/etc/nginx/sites-enabled/modmailerviewer-ip
viewer_hook=/etc/letsencrypt/renewal-hooks/deploy/modmailerviewer-nginx
for viewer_path in "$viewer_site" "$viewer_link" "$viewer_hook" /etc/letsencrypt/renewal/modmailerviewer-ip.conf /etc/letsencrypt/live/modmailerviewer-ip; do
    [[ ! -e "$viewer_path" && ! -L "$viewer_path" ]] || fail "Already exists: $viewer_path. Review the existing installation instead of overwriting it."
done
printf 'Install nginx and Snap Certbot, obtain an IP certificate for %s, and proxy HTTPS to 127.0.0.1:%s.\n' "$viewer_ip" "$viewer_port"
printf '%s\n' 'TCP 80 and 443 must be publicly reachable. Firewall/router rules are not changed.'
printf '%s\n' "This accepts Let's Encrypt's subscriber agreement: https://letsencrypt.org/repository/"
if ! "$viewer_yes"; then
    read -r -p 'Continue? Type yes: ' viewer_answer
    [[ "$viewer_answer" == yes ]] || fail 'Cancelled.'
fi
apt-get update
apt-get install -y nginx snapd ca-certificates
systemctl enable --now snapd.socket
snap wait system seed.loaded
if snap list certbot >/dev/null 2>&1; then
    snap refresh certbot
else
    snap install --classic certbot
fi
/snap/bin/certbot --version | python3 -c 'import re,sys; v=re.search(r"(\d+)\.(\d+)", sys.stdin.read()); sys.exit(0 if v and tuple(map(int,v.groups())) >= (5,4) else "Certbot 5.4 or newer is required.")'
nginx -t
viewer_created=false
cleanup() {
    viewer_status=$?
    if ((viewer_status != 0)) && "$viewer_created"; then
        rm -f -- "$viewer_link" "$viewer_site" "$viewer_hook"
        if nginx -t; then
            systemctl reload nginx || true
        fi
        printf '%s\n' 'Installation failed. Installer nginx files were removed. Installed packages and any issued certificate were retained.' >&2
    fi
}
trap cleanup EXIT
install -d -m 755 /var/www/modmailerviewer-acme /etc/nginx/sites-available /etc/nginx/sites-enabled
viewer_created=true
render_http > "$viewer_site"
ln -s "$viewer_site" "$viewer_link"
nginx -t
systemctl enable --now nginx
systemctl reload nginx
/snap/bin/certbot certonly --non-interactive --agree-tos --email="$viewer_email" \
    --webroot --webroot-path /var/www/modmailerviewer-acme \
    --preferred-profile shortlived --ip-address "$viewer_ip" --cert-name modmailerviewer-ip
render_https >> "$viewer_site"
nginx -t
systemctl reload nginx
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > "$viewer_hook" <<'EOF'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
EOF
chmod 755 "$viewer_hook"
systemctl enable --now snap.certbot.renew.timer
/snap/bin/certbot renew --cert-name modmailerviewer-ip --dry-run
trap - EXIT
printf '\nViewer URL: https://%s\nDiscord OAuth redirect: https://%s/oauth/callback\n' "$viewer_ip" "$viewer_ip"
printf 'Run [p]viewerset setup in the staff server. Choose HTTPS reverse proxy, port %s, and the viewer URL above.\n' "$viewer_port"
printf '%s\n' 'Keep TCP 80 open for certificate renewal and 443 for staff access. Keep the viewer port private.'
printf '%s\n' 'Certificates renew automatically through snap.certbot.renew.timer; nginx reloads after renewal.'
