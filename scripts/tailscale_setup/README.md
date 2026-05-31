

# Enabling Tailscale

1. Run node_tailscale_setup.sh, making sure to provide the correct tailscale auth-key for first time registration of a device. The auth-key can be found in your tailscale admin console

# Configuring Remote TMUX service

2. Make sure your machine was assigned the proper dns name in the tailscale admin console
3. Run ./tmux_gotty_setup.sh

# Connecting to remote TMUX console
After connecting to the tailnet, run:
4. In your web browser, run <tailscale_dns_name>:5004


# Fusion-Center tmux profile
TODO: Instead of hardcoding node ids to tienX, discover them from tailscale

5. 
