#!/bin/bash

# Install systemd service for Bonding Bot
# This script sets up the bonding-bot service to start on boot

set -e

echo "Installing Bonding Bot systemd service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (use sudo)"
    exit 1
fi

# Copy service file
echo "Copying service file to /etc/systemd/system/..."
cp /opt/bonding_bot/deploy/systemd/bonding-bot.service /etc/systemd/system/

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service to start on boot
echo "Enabling bonding-bot service..."
systemctl enable bonding-bot.service

# Start the service
echo "Starting bonding-bot service..."
systemctl start bonding-bot.service

# Check status
echo ""
echo "Service status:"
systemctl status bonding-bot.service --no-pager

echo ""
echo "✓ Bonding Bot service installed and started"
echo ""
echo "Useful commands:"
echo "  Status:  systemctl status bonding-bot"
echo "  Start:   systemctl start bonding-bot"
echo "  Stop:    systemctl stop bonding-bot"
echo "  Restart: systemctl restart bonding-bot"
echo "  Logs:    journalctl -u bonding-bot -f"
echo ""
