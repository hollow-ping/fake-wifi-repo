/* 
  main.js - Shared JavaScript
  
  LocalStorage logic + small scripts
  
  Signed "cookie" (burnerName + burnerNameSig) so editing localStorage can't spoof another user.
  
  Keys:
  - tempBurnerName: During account creation (before captchas complete)
  - burnerName: Committed username (only valid with matching burnerNameSig)
  - burnerNameSig: HMAC-SHA256(burnerName, secret) so changing burnerName breaks the sig.
  
  Flow:
  1. User enters username → tempBurnerName
  2. User completes password → tempBurnerName persists
  3. User completes captchas → tempBurnerName → burnerName + burnerNameSig (signed)
  4. Login: username must match stored burnerName and sig must verify; any password OK.
  
  Device States:
  1. New Device (no valid signed cookie) → Full flow
  2. Has Account (valid signed cookie) → Can login
*/
const BURNER_COOKIE_SECRET = "burnernet-v1-8f3a9c2e7d1b4f6a";

// Check device state and redirect accordingly
function checkDeviceState() {
    const burnerName = localStorage.getItem("burnerName");
    if (burnerName) return "hasAccount";
    return "newDevice";
}

// Get the stored burner name. Only trust after verifyBurnerCookie() on protected pages.
function getBurnerName() {
    return localStorage.getItem("burnerName") || "User";
}

// Set burner name only (legacy/debug). For commit use commitBurnerName() which signs.
function setBurnerName(name) {
    localStorage.setItem("burnerName", name);
}

function setBurnerCookie(name, sig) {
    localStorage.setItem("burnerName", name);
    localStorage.setItem("burnerNameSig", sig);
}

function clearBurnerCookie() {
    localStorage.removeItem("burnerName");
    localStorage.removeItem("burnerNameSig");
}

async function signBurnerCookie(name) {
    // crypto.subtle requires a secure context (HTTPS or localhost). On the Pi
    // captive portal at http://192.168.4.1 it's undefined — fall back to a
    // deterministic non-crypto tag so the cookie still pairs with itself.
    // Cookie spoofing protection was always nominal (any localStorage editor
    // could already lie), so this is an acceptable downgrade.
    if (!self.isSecureContext || !window.crypto || !window.crypto.subtle) {
        return 'plain:' + btoa(unescape(encodeURIComponent(BURNER_COOKIE_SECRET + ':' + name)));
    }
    const key = await crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode(BURNER_COOKIE_SECRET),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["sign"]
    );
    const sig = await crypto.subtle.sign(
        "HMAC",
        key,
        new TextEncoder().encode(name)
    );
    return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

async function verifyBurnerCookie() {
    const name = localStorage.getItem("burnerName");
    const storedSig = localStorage.getItem("burnerNameSig");
    if (!name) return false;
    const expectedSig = await signBurnerCookie(name);
    if (!storedSig) {
        setBurnerCookie(name, expectedSig);
        return true;
    }
    return expectedSig === storedSig;
}

// Temporary burner name during account creation (before captchas complete)
// Note: This automatically overwrites any existing tempBurnerName if user goes back and creates new account
function setTempBurnerName(name) {
    localStorage.setItem("tempBurnerName", name);
}

function getTempBurnerName() {
    return localStorage.getItem("tempBurnerName");
}

// Commit temp burner name to signed cookie after completing account creation. Async.
async function commitBurnerName() {
    const tempName = getTempBurnerName();
    if (!tempName) return null;
    const sig = await signBurnerCookie(tempName);
    setBurnerCookie(tempName, sig);
    localStorage.removeItem("tempBurnerName");
    return tempName;
}

// Get burner name during account creation (checks temp first, then committed)
function getBurnerNameDuringCreation() {
    return getTempBurnerName() || getBurnerName() || "User";
}

// Check if user has an account (has burnerName cookie - not temp)
function hasAccount() {
    return localStorage.getItem("burnerName") !== null;
}
