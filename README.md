# Fake WiFi Portal

A fake WiFi captive portal interface for testing and demonstration purposes.

## Deploying to GitHub Pages

This project can be easily deployed to GitHub Pages for testing on mobile devices.

### Setup Instructions

1. **Create a GitHub repository** (if you haven't already):
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

2. **Enable GitHub Pages**:
   - Go to your repository on GitHub
   - Click on **Settings** → **Pages**
   - Under **Source**, select **Deploy from a branch**
   - Choose **main** branch and **/ (root)** folder
   - Click **Save**

3. **Access your site**:
   - Your site will be available at: `https://YOUR_USERNAME.github.io/YOUR_REPO_NAME/`
   - It may take a few minutes for the site to be available after the first deployment

### Testing on Mobile

Once deployed, you can:
- Share the GitHub Pages URL with yourself via text/email
- Open it on your phone's browser
- Test all the functionality including the CAPTCHA verification

### Notes

- The site has been configured to work on GitHub Pages domains (github.io)
- All relative paths should work correctly
- The domain redirect logic has been updated to allow GitHub Pages

