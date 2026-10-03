#!/usr/bin/env bash
# Prepare a fresh AlmaLinux 9 server and install Dokploy. Run as root ON the server. Idempotent: safe to re-run.
#
#   ./server-setup-almalinux.sh --pubkey "ssh-ed25519 AAAA... you@laptop" [--advertise-addr 1.2.3.4] [--harden-ssh] [--dry-run]
#
# What it does, in order (each step prints what it is doing):
#   1 checks the OS and resources          2 updates, installs chrony/fail2ban/dnf-automatic, adds swap if RAM < 4 GB
#   3 creates sudo user "deploy" with YOUR public key      4 firewalld: allow ssh, http, https only
#   5 installs Docker CE (SELinux stays enforcing)         6 installs Dokploy and locks the panel port (3000) to this machine
#   7 (only with --harden-ssh) key-only SSH; do this ONLY after you tested `ssh deploy@host` from another terminal
set -euo pipefail

PUBKEY=""; ADVERTISE=""; HARDEN=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pubkey) PUBKEY="$2"; shift 2 ;;
    --advertise-addr) ADVERTISE="$2"; shift 2 ;;
    --harden-ssh) HARDEN=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '[dry-run] %s\n' "$*"; else eval "$@"; fi; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root"

say "1/7 Checking the system"
. /etc/os-release
[ "${ID:-}" = almalinux ] && [[ "${VERSION_ID:-}" == 9* ]] || die "expected AlmaLinux 9, found ${PRETTY_NAME:-unknown}"
MEM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
echo "OS: $PRETTY_NAME | RAM: ${MEM_MB} MB | free disk on /: ${DISK_GB} GB | SELinux: $(getenforce 2>/dev/null || echo n/a)"
[ "$MEM_MB" -ge 1800 ] || die "Dokploy needs at least 2 GB RAM"
[ "$DISK_GB" -ge 20 ] || die "need at least ~30 GB free disk (have ${DISK_GB} GB)"
for p in 80 443 3000; do
  if ss -ltn "( sport = :$p )" 2>/dev/null | grep -q LISTEN && ! docker ps 2>/dev/null | grep -q dokploy; then die "port $p is already in use"; fi
done
if [ -z "$ADVERTISE" ]; then ADVERTISE=$(curl -fsS -4 --max-time 8 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'); fi
[[ "$ADVERTISE" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not determine the public IPv4; pass --advertise-addr"
echo "Swarm/advertise address: $ADVERTISE"
if [ -n "$PUBKEY" ] && ! [[ "$PUBKEY" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+)\ [A-Za-z0-9+/=]+(\ [A-Za-z0-9@._+=:\ -]*)?$ ]]; then die "--pubkey does not look like a public key"; fi
[ "$HARDEN" = 0 ] || [ -n "$PUBKEY" ] || die "--harden-ssh requires --pubkey (otherwise you would lock yourself out)"

say "2/7 Updating and installing base packages"
run "dnf -y update"
run "dnf -y install chrony fail2ban fail2ban-firewalld dnf-automatic curl git tar firewalld policycoreutils-python-utils dnf-plugins-core"
run "systemctl enable --now chronyd"
run "sed -i 's/^apply_updates.*/apply_updates = yes/; s/^upgrade_type.*/upgrade_type = security/' /etc/dnf/automatic.conf"
run "systemctl enable --now dnf-automatic.timer"
if [ "$MEM_MB" -lt 4096 ] && ! swapon --show | grep -q .; then
  echo "RAM < 4 GB and no swap: adding a 2 GB swap file"
  run "fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab"
fi
run "printf '[sshd]\nenabled = true\nmaxretry = 4\nbantime = 1h\nfindtime = 10m\n' > /etc/fail2ban/jail.d/sshd.local"
run "systemctl enable --now fail2ban"

say "3/7 Admin user 'deploy' with your SSH key"
if [ -n "$PUBKEY" ]; then
  run "id deploy >/dev/null 2>&1 || useradd -m -G wheel deploy"
  run "install -d -m 700 -o deploy -g deploy /home/deploy/.ssh"
  run "grep -qxF '$PUBKEY' /home/deploy/.ssh/authorized_keys 2>/dev/null || echo '$PUBKEY' >> /home/deploy/.ssh/authorized_keys"
  run "chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys"
  run "install -d -m 700 /root/.ssh && (grep -qxF '$PUBKEY' /root/.ssh/authorized_keys 2>/dev/null || echo '$PUBKEY' >> /root/.ssh/authorized_keys) && chmod 600 /root/.ssh/authorized_keys"
  run "restorecon -R /home/deploy/.ssh /root/.ssh"
  echo "TEST NOW from another terminal:  ssh deploy@$ADVERTISE   (and: ssh root@$ADVERTISE)"
else
  echo "no --pubkey given: skipping (re-run with --pubkey when you have one)"
fi

say "4/7 Firewall: ssh, http, https only"
run "systemctl enable --now firewalld"
run "firewall-cmd --permanent --add-service=ssh --add-service=http --add-service=https"
run "firewall-cmd --permanent --remove-port=3000/tcp 2>/dev/null || true"
run "firewall-cmd --reload"

say "5/7 Docker CE"
run "dnf -y remove podman-docker docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine 2>/dev/null || true"
run "dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo"
run "dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin"
run "install -d /etc/docker && printf '{\"log-driver\":\"json-file\",\"log-opts\":{\"max-size\":\"10m\",\"max-file\":\"3\"}}\n' > /etc/docker/daemon.json"
run "systemctl enable --now docker"
run "docker run --rm hello-world | head -3"

say "6/7 Dokploy"
if [ "$DRY" = 0 ] && docker service ls 2>/dev/null | grep -q dokploy; then
  echo "Dokploy is already installed; skipping the installer"
else
  run "curl -fsSL https://dokploy.com/install.sh -o /root/dokploy-install.sh"
  echo "Installer saved to /root/dokploy-install.sh (read it if you like). Running it now."
  run "ADVERTISE_ADDR=$ADVERTISE sh /root/dokploy-install.sh"
fi
# Docker publishes ports with its own iptables rules, which firewalld does NOT filter, so closing 3000 in firewalld is not
# enough. This DOCKER-USER rule (drop forwarded traffic whose original destination port is 3000, unless it arrives on
# loopback) is BEST-EFFORT: it could not be tested against a real external client or a Swarm ingress port.
# Do not rely on it: create the admin account right after this script finishes, and run the "verify from OUTSIDE" check below.
run "cat > /etc/systemd/system/dokploy-panel-lockdown.service <<'UNIT'
[Unit]
Description=Block public access to the Dokploy panel port 3000 until HTTPS is set up
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'iptables -C DOCKER-USER -p tcp -m conntrack --ctorigdstport 3000 --ctdir ORIGINAL ! -i lo -j DROP 2>/dev/null || iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 3000 --ctdir ORIGINAL ! -i lo -j DROP'
ExecStop=/bin/sh -c 'iptables -D DOCKER-USER -p tcp -m conntrack --ctorigdstport 3000 --ctdir ORIGINAL ! -i lo -j DROP 2>/dev/null || true'
[Install]
WantedBy=multi-user.target
UNIT"
run "systemctl daemon-reload && systemctl enable --now dokploy-panel-lockdown.service"

say "7/7 SSH hardening"
if [ "$HARDEN" = 1 ]; then
  echo "Turning off password logins and root password login. Your current session stays open."
  run "install -d /etc/ssh/sshd_config.d"
  run "printf 'PasswordAuthentication no\nPermitRootLogin prohibit-password\nMaxAuthTries 3\n' > /etc/ssh/sshd_config.d/00-hardening.conf"
  run "sshd -t && systemctl reload sshd"
  echo "Open a NEW terminal and confirm 'ssh deploy@$ADVERTISE' works BEFORE closing this one."
else
  echo "skipped (pass --harden-ssh after you have tested key login)"
fi

say "Done"
cat <<EOF
Panel: the FIRST visitor can create the admin account, so do it NOW, before anything else. From your computer:
    ssh -L 3000:localhost:3000 deploy@$ADVERTISE      then open  http://localhost:3000   and create the admin account
(if port 3000 turns out to be reachable from outside in the check below, treat creating the admin as urgent)
Then in Dokploy: Settings -> Server -> Domain = dokp.hadifj.ir, HTTPS on (Let's Encrypt).
When HTTPS works, you may remove the lockdown:  systemctl disable --now dokploy-panel-lockdown   (the panel is then also on :3000)
Verify from OUTSIDE:  nc -zv $ADVERTISE 22 80 443  (open)   nc -zv -w3 $ADVERTISE 3000  (must time out)
EOF
