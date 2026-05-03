# Fake WiFi Portal

A fake WiFi captive portal interface for testing and demonstration purposes.

## GitHub Repository Information

**Repository URL:** https://github.com/hollow-ping/fake-wifi-repo

**GitHub Pages Settings:** https://github.com/hollow-ping/fake-wifi-repo/settings/pages

**Live Site URL:** https://hollow-ping.github.io/fake-wifi-repo/

## Project Overview

This is a static HTML/CSS/JavaScript project that simulates a WiFi captive portal authentication flow. It includes:
- Account creation flow
- CAPTCHA verification system with image selection
- Login functionality
- Connection simulation pages
- Intranet access pages

The project has been configured to work on GitHub Pages, with domain redirect logic updated to allow `github.io` domains.

## Deploying to GitHub Pages

This project is already set up for GitHub Pages deployment. Follow these steps to deploy:

### Initial Setup (if not already done)

1. **Create the initial commit** (if you haven't already):
   ```bash
   git commit -m "Initial commit - ready for GitHub Pages"
   ```

2. **Push to GitHub** (if you haven't already):
   ```bash
   git branch -M main
   git remote add origin https://github.com/hollow-ping/fake-wifi-repo.git
   git push -u origin main
   ```

### Enable GitHub Pages

1. Go to the GitHub Pages settings: https://github.com/hollow-ping/fake-wifi-repo/settings/pages
2. Under **Source**, select **Deploy from a branch**
3. Choose **main** branch and **/ (root)** folder
4. Click **Save**

### Access Your Site

- **Live URL:** https://hollow-ping.github.io/fake-wifi-repo/
- It may take a few minutes for the site to be available after the first deployment
- After each push to the `main` branch, GitHub Pages will automatically rebuild and deploy

### Testing on Mobile

Once deployed, you can:
- Share the GitHub Pages URL (`https://hollow-ping.github.io/fake-wifi-repo/`) with yourself via text/email
- Open it on your phone's browser
- Test all the functionality including:
  - Account creation flow
  - CAPTCHA verification with image selection
  - Login functionality
  - All navigation flows

## Technical Details

### Domain Configuration

The `index.html` file has been configured to work on GitHub Pages:
- Domain redirect logic allows `github.io` domains
- Also allows local IP addresses (`192.168.4.1`) for local testing
- Original domain redirect (`burner-net.com`) is preserved for production use

### File Structure

- `index.html` - Main entry point (portal splash screen)
- `create-account/` - Account creation flow pages
- `verify/` - CAPTCHA verification pages; `captcha.html` handles both challenges
- `verify/captcha-images/` - One subfolder per captcha set, each with `image-1.png`–`image-9.png`
- `connect/` - Connection simulation pages
- `intranet/` - Intranet access pages
- `js/` - JavaScript files including CAPTCHA logic and manifests
- `js/captcha-manifest.json` - Captcha config: `randomOrder` flag + `captchas` array (each entry has `folder` and `question`)
- `css/` - Stylesheet files
- `setup-pi.sh` - Raspberry Pi setup script (hostapd, dnsmasq, lighttpd, iptables)
- `captive-portal-files/` - OS captive portal probe files (hotspot-detect, generate_204, connecttest)

### Relative Paths

All paths in the project use relative URLs, which work correctly on GitHub Pages. The project structure is maintained when deployed.

## Notes for LLMs

- This project is a static website that simulates a WiFi captive portal
- It uses localStorage for session management (burnerName, tempBurnerName)
- The CAPTCHA system uses `verify/captcha.html` for both challenges (single page, 2-step flow)
- CAPTCHA images live in `verify/captcha-images/<folder>/image-1.png` through `image-9.png` (pre-split, always exactly 9)
- `js/captcha-manifest.json` controls which captcha sets are active: top-level `randomOrder` (bool) shuffles tile display order; `captchas` array maps each folder to its question; 2 sets are picked randomly per session
- To add a new captcha set: add 9 PNGs named `image-1.png`–`image-9.png` to a new subfolder under `verify/captcha-images/`, then add an entry to `captchas` in the manifest
- GitHub Pages serves the site from the root directory
- The repository is public and the site is accessible at the GitHub Pages URL above
- All functionality is client-side JavaScript - no backend required
- Pi deployment: `setup-pi.sh` configures hostapd (AP on `uap0`), dnsmasq (DNS wildcard → 192.168.4.1), lighttpd (portal + captive portal probe redirects), and iptables (port 80 DNAT, port 443 fast-reject)

# Sync Macbook to Pi

`rsync -avz --exclude='.git' --exclude='.DS_Store' --exclude='.vscode' --exclude='.idea' /Users/john/Documents/Projects/fake-wifi/fake-wifi-repo/ j@jp6.local:~/fake-wifi-repo/`


