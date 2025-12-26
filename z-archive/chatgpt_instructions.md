


python3 -m http.server 8000
http://localhost:8000/index.html







Absolutely — here is a clean, thorough, single-file MARKDOWN document that captures:
	•	Your full concept
	•	Page flow & UX
	•	Technical architecture
	•	LocalStorage logic
	•	Retro styling plan
	•	Pi deployment notes
	•	File/folder structure
	•	Implementation blueprint
	•	All the creative details we’ve brainstormed

You can copy/paste this directly into your GitHub repo as your README.md.

⸻

Burner WiFi Portal — Project Overview & Implementation Guide

A fake WiFi login experience for a Burner event, inspired by the trauma of burner ticket queues, broken corporate intranets, parody password screens, silly captchas, and dead-end tech portals.

This project creates a local intranet hosted on a Raspberry Pi Zero 2 W.
Users join the Pi’s hotspot and are taken through a chaotic, absurd, hilarious multi-step “login process” before reaching a secret internal network containing polls, forms, jokes, and a tiny forum.

Everything is done using static HTML + CSS + JS, served by the Pi.
User progress is tracked using localStorage to unlock the intranet after the first “run.”

This README explains how the system works and how to build it.

⸻

1. High-Level Concept

When someone connects to the WiFi network:
	1.	They see a fake corporate / Burner-tech splash page.
	2.	They create a meaningless “account.”
	3.	They go through impossible password requirements (parody of online games).
	4.	They complete ridiculous captchas like “select all images containing hope”.
	5.	They enter the Burner Queue, which starts them at a huge number and then instantly jumps to #1.
	6.	They solve a fake source-code error for a “satellite connection.”
	7.	They wait through a fake loading bar with absurd tech status logs.
	8.	Connection fails (intentionally).
	9.	They are given the option to enter the Local Intranet.
	10.	The intranet is a retro pixel-style site containing:
	•	Funny polls
	•	Strange forms
	•	A tiny fake forum
	•	Random internally branded nonsense

Once a device reaches the intranet, it is flagged as “intranet-access” via localStorage.
From then on, that device skips the entire login circus and gets immediately routed to the intranet homepage.

⸻

2. Tech Stack

Everything is static:
	•	HTML – Page structure
	•	CSS – Retro pixel aesthetic (NES.css, 98.css, or your custom CSS)
	•	JavaScript – Light interactivity and state storage
	•	localStorage – Tracks:
	•	burnerName
	•	hasIntranetAccess

Served by:
	•	Raspberry Pi Zero 2 W running:
	•	hostapd (WiFi AP)
	•	dnsmasq (DNS hijack)
	•	lighttpd or nginx (static file webserver)

No backend needed:
	•	No PHP, Python server, or database
	•	No framework
	•	No accounts/passwords stored anywhere except the user’s own device

⸻

3. Folder Structure

This repo layout is simple and clear:

burner-wifi-portal/
├─ index.html              # splash / welcome
├─ create.html             # "create account" name + absurd password rules
├─ captcha1.html           # first joke captcha
├─ queue.html              # burner queue (fast drop to #1)
├─ captcha2.html           # second captcha (quick, silly)
├─ debug.html              # fake source code “bug” to fix
├─ connecting.html         # loading bar + funny logs → "connection failed"
├─ intranet/
│  ├─ index.html           # main intranet home (polls, forms, forum)
│  ├─ polls.html
│  ├─ forms.html
│  └─ forum.html
├─ css/
│  └─ main.css             # global retro styling (pixel fonts + colors)
└─ js/
   └─ main.js              # shared JS (localStorage logic + small scripts)

You can, of course, change page names or collapse pages if you want fewer steps.

⸻

4. Page-by-Page UX Flow

This is the final agreed sequence. Feel free to modify, but this is a good baseline.

⸻

4.1 index.html — Splash Screen

Purpose:
The captive portal redirects here automatically.

Logic:
	•	If localStorage.hasIntranetAccess === "true" → instantly redirect to intranet/index.html
	•	Otherwise show:
	•	Retro header: “BURNERNET AUTH PORTAL”
	•	Button: [Create Account] → create.html

⸻

4.2 create.html — “Create Account” Screen

UI elements:
	•	Username field (“Choose your Network Handle”)
	•	Password field
	•	List of absurd password requirements, like:
	•	Must include >24 characters
	•	Must contain a haiku
	•	Must include 1 lowercase, 1 uppercase, 1 number, 1 emoji, 1 life regret
	•	Must be unique in the multiverse
	•	“Show me the requirements” toggle
	•	Hidden “use insecure password” option if they fail requirements

Logic:
	•	On submit:
	•	Save name into localStorage:

localStorage.setItem("burnerName", handleInput.value);


	•	Redirect to: captcha1.html

No real password validation.

⸻

4.3 captcha1.html — First Joke Captcha

Examples:
	•	“Select all images that contain hope.”
	•	“Which of these contain the essence of Burner?”
	•	“Choose all squares where the AI achieved enlightenment.”

Behavior:
	•	No correct answers
	•	After one or two incorrect attempts → show:
[Override: Admin Only] button

On override click: → queue.html

⸻

4.4 queue.html — Fake Burner Queue

The highlight of this experience.

UI:
	•	Title: “BURNERNET AUTH QUEUE”
	•	Big text:

You are in place #1,406 in the login queue.
Estimated wait: 14 minutes...


	•	Walking-man animation (emoji or pixel sprite)
	•	Scrolling fake log lines

Logic:
	•	On load:
	•	Random big queue number: 1000–3000
	•	After ~1s → drop to ~40
	•	After ~1.4s → drop to ~5
	•	After ~1.6s → drop to 1
	•	After ~2.5s → show “Connecting…”
	•	After ~3s → redirect to captcha2.html

Users will laugh because it mimics the real Burner ticket queue.

⸻

4.5 captcha2.html — Second Mini Captcha

Examples:
	•	“Prove you are not a robot: explain the meaning of dust in under 5 words.”
	•	“Drag the star into the vortex” (but the vortex moves)
	•	“Check the box that best describes your vibe today.”

After pressing continue:
→ debug.html

⸻

4.6 debug.html — Fake Source Code Error

UI idea:

A fake code editor with retro styling, showing something like:

if (connection.stable && user.trustworthy && vibes >= 7.4) {
    connectToSatellite();
} else {
    throw new Error("VibeError: vibes_not_high_enough");
}

Highlight the failing line, red underline, etc.

Button:
	•	[Apply Unreviewed Hotfix]
	•	[Comment Out Sanity Checks]

After they click:
→ Redirect to connecting.html

⸻

4.7 connecting.html — Loading Bar + Funny Messages → Failure

UI:
	•	Title: “Connecting to External Internet…”
	•	Retro loading bar
	•	Underneath it, rotating funny logs:
	•	“Negotiating with cloud deity…”
	•	“Normalizing glitter distribution…”
	•	“Measuring dust density…”
	•	“Validating vibes…”

Logic:
	•	Slowly fill progress bar
	•	At ~80–95%:
→ Replace logs with a big red error:

External connection failed.


	•	Set localStorage.hasIntranetAccess = "true"
	•	Show button: [Enter Local Intranet] → /intranet/index.html

This is the “unlock moment.”

⸻

4.8 /intranet/index.html — Local Network Intranet

This is your retro paradise.

Features:
	•	Pixel UI (NES.css or 98.css)
	•	Username displayed (burnerName)
	•	Links to:
	•	/intranet/polls.html
	•	/intranet/forms.html
	•	/intranet/forum.html

Everything is static, but you can use JS to:
	•	Save poll submissions in localStorage
	•	Save forum posts per device
	•	Show persistent “messages” and replies

Users feel like they’re in a weird little internal social network.

⸻

5. Visual Style — Retro Pixel Aesthetic

Your aesthetic goal:
retro pixel, early-internet intranet, 8-bit UI, mobile-friendly.

Use:

Pixel font:
	•	Press Start 2P
	•	VT323
	•	IBM VGA 8x16
	•	Or any other hosted pixel font

CSS frameworks (optional):
	•	NES.css — Nintendo-style UI
	•	98.css — Windows 98 UI
	•	Terminal.css — green/black hacker vibe
	•	Water.css — minimal automatic styling

Combine with:
	•	big chunky borders
	•	minimal color palette
	•	fake system messages
	•	pixel art icons
	•	emoji icons for walking man
	•	monospaced code panels

⸻

6. LocalStorage Behavior

Two keys:

Key 1 — burnerName

Saved once when they “create account.”

Used for:
	•	Displaying in intranet header
	•	Displaying in forum posts
	•	Greeting message on intranet

Key 2 — hasIntranetAccess

Set to "true" on first completion of the whole flow.

Every time index.html loads, check:

if (localStorage.getItem("hasIntranetAccess") === "true") {
    window.location.href = "/intranet/index.html";
}

This skips:
	•	create account
	•	captcha
	•	queue
	•	debug
	•	loading animation

for repeat visits on same device.

⸻

7. Deployment on Raspberry Pi

You will use:
	•	Pi Zero 2 W
	•	Battery (Jackery) — extremely low power
	•	(Optional) USB WiFi antenna for range boost

Services:
	•	hostapd
Broadcasts the fake SSID (“CosmicNet-Portal”, “BurnerLAN”, etc.)
	•	dnsmasq
Redirects ALL DNS to your Pi → captive portal behavior
	•	lighttpd / nginx
Serves HTML/CSS/JS files

Deployment steps:
	1.	Copy your repo into /var/www/html/
	2.	Remove any pre-existing files there
	3.	Configure captive portal to always redirect to index.html
	4.	Test on mobile devices in airplane mode + WiFi

⸻

8. Rainproof Hardware Notes (your enclosure)

Summarizing your enclosure design:
	•	PETG one-piece outer shell
	•	Solid top
	•	Bottom inset lid
	•	Power cable exits downward
	•	Cable gland or rubber grommet
	•	Vent slits facing downward
	•	USB antenna poking up through a “chimney”
	•	Optional aluminum HVAC tape on the inside seams
	•	Very low heat from Pi Zero, safe

⸻

9. Summary of Your Creative Requirements

Your project includes:
	•	A fake burner-tech login flow
	•	Retro pixel aesthetics
	•	A fake account creation screen (no real accounts)
	•	Ridiculous password rules
	•	Silly captchas
	•	Burner queue parody (instant drop from #2,000 to #1)
	•	Fake JS error/debug page
	•	Fake satellite connection screen
	•	Loading bar with silly logs
	•	Predictable failure
	•	Link to “Local Intranet”
	•	A small intranet with polls, forms, and a goofy forum
	•	A persistent “intranet access” flag stored client-side
	•	All static, fast, lightweight
	•	Hosted on a Pi Zero AP with a fun enclosure
	•	Fully offline and local to the event

This is deeply on-theme for a Burner event: confusing, funny, surprising, and then charming.

⸻

10. Next Steps (Recommended)
	1.	Create the repo with the provided structure
	2.	Make a minimal version of:
	•	index.html
	•	create.html
	•	queue.html
	•	intranet/index.html
	3.	Add localStorage checks
	4.	Layer the retro CSS
	5.	Build the redirect chain + queue logic
	6.	Test locally with python -m http.server
	7.	Deploy to Pi
	8.	Put it into your waterproof enclosure
	9.	Add your silly intranet content

You’re ready.

If you want, I can also generate a starter template for each page or help you pick the retro CSS framework and vibe.